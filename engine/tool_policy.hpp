#pragma once
#include <nlohmann/json.hpp>
#include <cmath>
#include <set>
#include <string>
#include "input.hpp"

namespace lens {
// A deliberately narrow deterministic boundary, not a general JSON Schema engine.
// Only save_event proposals are registered. Schemas support one explicit type:
// object/properties/required, array/items, string, integer, number, boolean, null.
// Object extras are always forbidden (including when additionalProperties is
// omitted). Only explicit false is accepted. Description/title are annotations.
// All other keywords, including $ref, patterns, formats, unions and defaults,
// fail closed. This validates structure and native safety flags, not truth,
// semantic date validity, entity identity, user consent or execution authority.
class ToolPolicy {
    using json=nlohmann::json;
    json schemas_=json::object();
    static constexpr unsigned max_depth=8;
    static constexpr std::size_t max_properties=64,max_items=1024,max_calls=16;

    static void only_keys(const json& value,const std::set<std::string>& keys) {
        if(!value.is_object())throw Error("invalid_tool_schema");
        for(const auto& [key,unused]:value.items()) {
            (void)unused;
            if(!keys.contains(key))throw Error("unsupported_schema");
        }
    }
    static bool valid_text(const json& value,std::size_t limit,bool empty=false) {
        if(!value.is_string())return false;
        const auto& text=value.get_ref<const std::string&>();
        return (empty||!text.empty())&&text.size()<=limit&&text.find('\0')==std::string::npos;
    }
    static void check_schema(const json& schema,unsigned depth=0) {
        if(depth>max_depth||!schema.is_object()||!schema.contains("type")||!schema["type"].is_string())
            throw Error("invalid_tool_schema");
        const auto type=schema["type"].get<std::string>();
        std::set<std::string> keys{"type","description","title"};
        if(type=="object")keys.insert({"properties","required","additionalProperties"});
        else if(type=="array")keys.insert("items");
        else if(type!="string"&&type!="integer"&&type!="number"&&type!="boolean"&&type!="null")
            throw Error("unsupported_schema_type");
        only_keys(schema,keys);
        for(const auto* key:{"description","title"})
            if(schema.contains(key)&&!valid_text(schema[key],8192,true))throw Error("invalid_tool_schema");
        if(type=="object") {
            if(!schema.contains("properties")||!schema["properties"].is_object()||schema["properties"].size()>max_properties)
                throw Error("invalid_tool_schema");
            if(schema.contains("additionalProperties")&&
                (!schema["additionalProperties"].is_boolean()||schema["additionalProperties"].get<bool>()))
                throw Error("unsupported_schema");
            for(const auto& [name,node]:schema["properties"].items()) {
                if(name.empty()||name.size()>256||name.find('\0')!=std::string::npos)throw Error("invalid_tool_schema");
                check_schema(node,depth+1);
            }
            if(schema.contains("required")) {
                if(!schema["required"].is_array()||schema["required"].size()>max_properties)throw Error("invalid_tool_schema");
                std::set<std::string> seen;
                for(const auto& name:schema["required"]) {
                    if(!valid_text(name,256)||!schema["properties"].contains(name.get<std::string>())||
                       !seen.insert(name.get<std::string>()).second)throw Error("invalid_tool_schema");
                }
            }
        } else if(type=="array") {
            if(!schema.contains("items"))throw Error("invalid_tool_schema");
            check_schema(schema["items"],depth+1);
        }
    }
    static std::string check_value(const json& schema,const json& value,unsigned depth=0) {
        if(depth>max_depth)return "argument_depth_limit";
        const auto type=schema["type"].get<std::string>();
        if(type=="object") {
            if(!value.is_object())return "argument_type_mismatch";
            if(value.size()>max_properties)return "argument_size_limit";
            const auto& properties=schema["properties"];
            if(schema.contains("required"))for(const auto& name:schema["required"])
                if(!value.contains(name.get<std::string>()))return "missing_required_argument";
            for(const auto& [name,item]:value.items()) {
                if(!properties.contains(name))return "extra_argument";
                const auto reason=check_value(properties[name],item,depth+1);
                if(!reason.empty())return reason;
            }
            return {};
        }
        if(type=="array") {
            if(!value.is_array())return "argument_type_mismatch";
            if(value.size()>max_items)return "argument_size_limit";
            for(const auto& item:value) {
                const auto reason=check_value(schema["items"],item,depth+1);
                if(!reason.empty())return reason;
            }
            return {};
        }
        const bool correct=(type=="string"&&valid_text(value,131072,true))||
            (type=="integer"&&value.is_number_integer())||
            (type=="number"&&value.is_number()&&std::isfinite(value.get<double>()))||
            (type=="boolean"&&value.is_boolean())||(type=="null"&&value.is_null());
        return correct?std::string{}:std::string{"argument_type_mismatch"};
    }
    static std::string uncertainty(const json& value) {
        for(const auto* flag:{"negation","uncertain","uncertainty","needs_confirmation","requires_confirmation"}) {
            if(value.contains(flag)) {
                if(!value[flag].is_boolean())return "invalid_validation_flag";
                if(value[flag].get<bool>())return std::string{"native_"}+flag;
            }
        }
        return {};
    }
    static std::string envelope_reason(const json& proposal) {
        if(!proposal.is_object()||!proposal.contains("function_calls")||!proposal["function_calls"].is_array()||
           (proposal.contains("suppressed_calls")&&!proposal["suppressed_calls"].is_array()))return "invalid_proposal";
        if(!proposal.contains("success")||!proposal["success"].is_boolean()||!proposal["success"].get<bool>())return "native_failure";
        for(const auto* field:{"error","error_code"})
            if(proposal.contains(field)&&!proposal[field].is_null())return "native_failure";
        if(!proposal.contains("type")||!proposal["type"].is_string()||
           (proposal["type"]!="call"&&proposal["type"]!="respond"))return "invalid_proposal_type";
        if(proposal["type"]!="call"&&!proposal["function_calls"].empty())return "invalid_proposal_type";
        auto reason=uncertainty(proposal);
        if(!reason.empty())return reason;
        if(proposal.contains("validation")) {
            const auto& validation=proposal["validation"];
            if(!validation.is_object())return "invalid_validation";
            const std::set<std::string> known{"ungrounded","negation","uncertain","uncertainty","needs_confirmation","requires_confirmation"};
            for(const auto& [key,unused]:validation.items()) {
                (void)unused;
                if(!known.contains(key))return "unsupported_validation_flag";
            }
            reason=uncertainty(validation);
            if(!reason.empty())return reason;
            if(validation.contains("ungrounded")) {
                if(!validation["ungrounded"].is_array())return "invalid_validation";
                for(const auto& path:validation["ungrounded"])if(!valid_text(path,1024))return "invalid_validation";
                if(!validation["ungrounded"].empty())return "native_ungrounded";
            }
        }
        if(!proposal.contains("confidence")||!proposal["confidence"].is_number())return "confidence_unavailable";
        const auto confidence=proposal["confidence"].get<double>();
        if(!std::isfinite(confidence)||confidence<0||confidence>1)return "invalid_confidence";
        // Mirror only the upstream refusal floor. This is not a calibrated Lens
        // quality/authorization threshold, and acceptance never executes a call.
        if(confidence<0.1)return "native_low_confidence";
        if(proposal["function_calls"].size()>max_calls||
           (proposal.contains("suppressed_calls")&&proposal["suppressed_calls"].size()>max_calls))return "call_count_limit";
        return {};
    }
    std::string call_reason(const json& call) const {
        if(!call.is_object()||call.size()!=2||!call.contains("name")||!valid_text(call["name"],256)||
           !call.contains("arguments"))return "invalid_call_shape";
        const auto name=call["name"].get<std::string>();
        if(!schemas_.contains(name))return "unknown_tool";
        return check_value(schemas_[name],call["arguments"]);
    }
public:
    explicit ToolPolicy(const json& tools) {
        if(!tools.is_array()||tools.empty()||tools.size()>1)throw Error("invalid_tool_schema");
        for(const auto& entry:tools) {
            const json* tool=&entry;
            if(entry.is_object()&&entry.contains("function")) {
                only_keys(entry,{"type","function"});
                if(!entry.contains("type")||entry["type"]!="function")throw Error("invalid_tool_schema");
                tool=&entry["function"];
            }
            only_keys(*tool,{"name","description","parameters"});
            if(!tool->contains("name")||!valid_text((*tool)["name"],256))throw Error("invalid_tool_schema");
            const auto name=(*tool)["name"].get<std::string>();
            if(name!="save_event")throw Error("unknown_tool_schema");
            if(tool->contains("description")&&!valid_text((*tool)["description"],8192,true))throw Error("invalid_tool_schema");
            if(!tool->contains("parameters"))throw Error("invalid_tool_schema");
            check_schema((*tool)["parameters"]);
            if((*tool)["parameters"]["type"]!="object")throw Error("invalid_tool_schema");
            schemas_[name]=(*tool)["parameters"];
        }
    }
    json evaluate(const json& proposal) const {
        json accepted=json::array(),blocked=json::array();
        const auto common=envelope_reason(proposal);
        if(proposal.is_object()&&proposal.contains("function_calls")&&proposal["function_calls"].is_array()) {
            for(const auto& call:proposal["function_calls"]) {
                const auto reason=common.empty()?call_reason(call):common;
                if(reason.empty())accepted.push_back(call);
                else blocked.push_back({{"call",call},{"reason",reason}});
            }
        }
        if(proposal.is_object()&&proposal.contains("suppressed_calls")&&proposal["suppressed_calls"].is_array())
            for(const auto& call:proposal["suppressed_calls"])blocked.push_back({{"call",call},{"reason","native_suppressed"}});
        if(!common.empty()&&blocked.empty())blocked.push_back({{"call",nullptr},{"reason",common}});
        auto response=proposal.is_object()?proposal:json::object();
        response["proposal"]=proposal;
        response["function_calls"]=accepted;
        response["accepted_calls"]=accepted;
        response["blocked_calls"]=blocked;
        response["policy"]={{"version",1},{"executed",false}};
        return response;
    }
};
}
