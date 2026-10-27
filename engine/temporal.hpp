#pragma once
#include <chrono>
#include <optional>
#include <string>
namespace lens {
// A time window interpreted from a natural-language question ("last week", "昨天", "el mes pasado").
// Bounds are UTC; calendar arithmetic happens in the caller's fixed UTC offset at `now`.
struct TimeWindow {
    std::chrono::sys_seconds from,to; // half-open [from,to)
    std::string phrase;               // the matched expression, reported back to the caller
    std::string kind;                 // day, week, month, year, days_ago
};
// Returns nothing when the question has no recognised, unambiguous time expression.
// Deliberately excluded: Hindi "कल" (yesterday or tomorrow) and other context-dependent words.
std::optional<TimeWindow> interpret_time(const std::string& question,std::chrono::sys_seconds now,int utc_offset_minutes);
std::string iso_utc(std::chrono::sys_seconds t);
}
