"""Download the public comparison baselines (evaluation only; never shipped, never trained on) into
models/baselines/<org>--<name> and pin each one in lens_model/manifest/baselines-lock.json (revision, license,
file sha256). Only weights, configs and tokenizers are fetched (no remote code).
Usage: .venv-train\\Scripts\\python.exe lens_model/eval/fetch_baselines.py [repo ...]
"""
import hashlib
import json
from pathlib import Path
import sys
from huggingface_hub import HfApi,snapshot_download
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'models/baselines'
LOCK=ROOT/'lens_model/manifest/baselines-lock.json'
BASELINES={  # repo: (role, license as published on the model card)
    'Qwen/Qwen3-Reranker-0.6B':('answerability judge (reranker)','apache-2.0'),
    'Qwen/Qwen3-Reranker-4B':('answerability judge (reranker)','apache-2.0'),
    'BAAI/bge-reranker-v2-m3':('answerability judge (cross-encoder)','apache-2.0'),
    'Qwen/Qwen2.5-1.5B-Instruct':('answerability judge (instruct LLM)','apache-2.0'),
    'Qwen/Qwen3-1.7B':('answerability judge (instruct LLM)','apache-2.0'),
    'Qwen/Qwen3-4B':('answerability judge (instruct LLM)','apache-2.0'),
    'Qwen/Qwen3-Embedding-0.6B':('retrieval embedding','apache-2.0'),
    'BAAI/bge-m3':('retrieval embedding','mit'),
    'intfloat/multilingual-e5-small':('retrieval embedding (the model Lens ships, FP32 reference)','mit'),
    'intfloat/multilingual-e5-base':('retrieval embedding','mit'),
    'intfloat/multilingual-e5-large-instruct':('retrieval embedding','mit'),
    'ibm-granite/granite-embedding-278m-multilingual':('retrieval embedding','apache-2.0'),
    'Snowflake/snowflake-arctic-embed-l-v2.0':('retrieval embedding','apache-2.0'),
}
PATTERNS=['*.json','*.safetensors','*.txt','*.model','tokenizer*','sentencepiece*','merges.txt','vocab*','1_Pooling/*','modules.json']


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()


def main():
    repos=sys.argv[1:] or list(BASELINES);api=HfApi()
    lock=json.loads(LOCK.read_text(encoding='utf-8')) if LOCK.exists() else {'note':'evaluation baselines only; not shipped','models':{}}
    for repo in repos:
        rev=api.model_info(repo).sha;dest=OUT/repo.replace('/','--')
        names=[s.rfilename for s in api.model_info(repo,files_metadata=False).siblings]
        extra=[] if any(n.endswith('.safetensors') for n in names) else ['pytorch_model.bin']  # loaded weights-only (torch>=2.6)
        snapshot_download(repo,revision=rev,local_dir=dest,allow_patterns=PATTERNS+extra,ignore_patterns=['onnx/*','*.onnx','openvino/*'])
        files={str(p.relative_to(dest)).replace('\\','/'):sha(p) for p in sorted(dest.rglob('*')) if p.is_file() and '.cache' not in p.parts}
        lock['models'][repo]={'revision':rev,'role':BASELINES[repo][0],'license':BASELINES[repo][1],'files':files}
        LOCK.write_text(json.dumps(lock,indent=1),encoding='utf-8')
        print(repo,rev[:12],sum((dest/f).stat().st_size for f in files)//2**20,'MB',flush=True)


if __name__=='__main__':main()
