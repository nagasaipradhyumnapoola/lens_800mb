"""A real public-audio -> native ASR -> SQLCipher -> reopen -> source retrieval demo.

Uses the public JFK clip supplied by whisper.cpp, not a physical microphone or invented memory.
"""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]


def call(db,requests):
    result=subprocess.run([str(ROOT/'build/engine/Release/lens-engine.exe'),'--db',str(db)],
                          input=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in requests),
                          encoding='utf-8',capture_output=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stderr)
    return [json.loads(x) for x in result.stdout.splitlines() if x.startswith('{')]


def main():
    folder=ROOT/'artifacts'/('native-demo-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True)
    db=folder/'public-fixture-memory.db'
    source_id='public-jfk-fixture'
    ingest=call(db,[{'op':'ingest_audio','consent':True,'id':source_id,
                    'audio':str(ROOT/'third_party/whisper.cpp/samples/jfk.wav'),
                    'model':str(ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin'),
                    'language':'en','timestamp':datetime.now(timezone.utc).isoformat(),
                    'device':'windows-development-fixture','kind':'public_audio_import',
                    'provenance':'whisper.cpp public JFK fixture; historical speech, not a live recording'}])[0]
    assert ingest['ok'],ingest
    # A fresh native process must decrypt and retrieve the original source.
    search,missing,stats=call(db,[{'op':'search','query':'country'},
                                 {'op':'search','query':'nonexistent-memory-999'}, {'op':'stats'}])
    assert search['ok'] and search['sources'][0]['id']==source_id,search
    assert search['sources'][0]['text']==ingest['transcript']['text']
    assert missing['not_found'] and stats['source_count']==1
    raw=db.read_bytes()
    assert b'SQLite format 3' not in raw[:16]
    assert b'fellow Americans' not in raw
    report={'fixture_kind':'public recorded historical speech, not physical-watch testing',
            'ingest':ingest,'retrieval_after_process_restart':search,'unanswerable':missing,
            'database':str(db),'database_bytes':len(raw),'sqlcipher':stats['cipher_version'],
            'plaintext_signature_absent':True,'result':'PASS'}
    (ROOT/'reports/native-demo.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
