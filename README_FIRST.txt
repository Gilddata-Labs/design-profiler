GILDDATA DESIGN DATA PROFILER  -  read this first

WHAT IT DOES
It measures a folder of design files (CAD, BIM, EDA) and writes ONE zip of numbers about them: how many files of each type,
their sizes and dates, which parts each assembly uses, how many sheets each AutoCAD drawing has. It never copies, uploads or
keeps the contents of any file. File and folder names are replaced by codes unless you choose otherwise.
It works only on this computer. It has no internet connection and sends nothing anywhere: you send us the zip yourself.

BEFORE YOU START
1. Extract this whole zip (right click, Extract All). Do not run it from inside the zip.
2. Check the download: the release page lists a SHA256 checksum for this zip. On Windows:
     certutil -hashfile gilddesign-<version>-supplier.zip SHA256
   On Mac or Linux:  shasum -a 256 gilddesign-<version>-supplier.zip
   The number must match the one we sent you.

THE EASY WAY (a page in your browser, this computer only)
   Windows: double click run-ui.bat        Mac / Linux: double click run-ui.command
   Pick the folder, then click Step 1, then Step 2, then download the zip.

THE COMMAND WAY
   python gilddesign.py check   "D:\Projects"     a quick test: will it run, how big is the job (opens no file)
   python gilddesign.py quick   "D:\Projects"     Step 1: files per type and size (opens no file, very fast)
   python gilddesign.py extract "D:\Projects"     Step 2: the full profile
   (Windows: run.bat starts Step 2 when you drag a folder onto it. Mac / Linux: run.command.)
   Each folder directly inside the one you choose counts as one project.

WHAT TO SEND US
   The profile_<folder>_<date>.zip from the "output" folder (and the quick_ zip from Step 1).
   Also useful: run_stats_<folder>_<date>.zip (timings and machine type only, no names).
   KEEP PRIVATE: name_map_<folder>_<date>.zip turns the codes back into your real names. Never send it unless you want us to see
   the real names.

FINGERPRINTS (only if GildData asks you to)
   Add --fingerprint to the extract command. For each design file it adds a short code computed from its size and its first and last
   64 KB, so GildData can tell when the same file is offered twice. The code cannot be turned back into the file.

NAMES
   By default every project, folder and file name in the result is a code (extensions are kept). The same name gets the same code
   in Step 1, Step 2 and later runs on this computer. Only if you agree to share real names: untick "Anonymise" on the page, or add
   --real-names on the command line. The zip records which choice was made.

IF IT STOPS
   Crash, power cut, Ctrl+C: start it again with the same settings. It continues from the last saved point. To start over, tick
   "Start from scratch" or add --fresh.

IF SOMETHING GOES WRONG
   Send us output\error_log.txt (your folder paths are removed from it) and the check_<date>.json from "gilddesign check".

DOCKER (optional, the most sealed way: the container cannot write to your folder or reach the network)
   Mac / Linux: ./run-docker.sh /path/to/folder        Windows: drag the folder onto run-docker.bat
   The first start builds the image, which needs internet once to download Python.

You can open every .py file in Notepad to read exactly what it does, and every CSV in the zip to see exactly what you send.
