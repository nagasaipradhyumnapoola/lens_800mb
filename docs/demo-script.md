# Repeatable demonstrations

1. Run `.venv\Scripts\python.exe scripts/native-demo.py` from D:\Lens. It uses the public JFK fixture,
   not a user's voice. Inspect reports/native-demo.json for the original transcript, source ID,
   import timestamp and SQLCipher version. The script closes/reopens the native process before search.
2. For Mandarin, use `scripts/lens.ps1 -Action ImportAudio -Language zh -SourcePath <authorized WAV>`.
   Run Search for a literal substring present in the actual result. The original script and text
   must be returned from encrypted persistence. Never claim ASR output is a perfect transcript.
3. For a user-supplied text crop, ImportImage chooses v6 tiny for configured Latin/Han languages or
   v5 Devanagari for Hindi. Search a returned word. Current OCR tests are synthetic crop tests.
4. Extract returns an untrusted Needle proposal and never executes its function calls. Negation
   and multilingual failures are visible in the extraction report; do not demo autonomous actions.
5. Inspect native-tests, input-safety and CJK regression logs. The privacy tests use synthetic
   markers, swap protected keys to test rejection, and kill/reopen a process to test WAL recovery.
6. Inspect windows-endurance.json: the timed loop reloads/unloads a native speech model and repeats
   actual ingest/search. It does not simulate progress or reuse hardcoded transcripts.

No native API calls in these processing paths require a cloud model endpoint. Network-firewalled
air-gap certification remains pending; opting out of telemetry is not a packet-level audit.
Do not disable system networking or change firewall policy merely to run this demonstration.

Not demonstrated: live watch microphone, watch battery/thermals, phone/laptop pairing or sync,
WhatsApp/email/history access, arbitrary natural-language QA, screen observation or consumer UI.
Those are not secretly available through these CLI controls.
