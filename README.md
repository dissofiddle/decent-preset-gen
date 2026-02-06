# decent-preset-gen
Simple python script to generate decent sample instrument from wav samples (multi)


This script is made to generate decent sampler preset from a collections of file with root
note and optionnally velocity (ex; Moog_A1.wav, Moog_b1.wav, Moog_C#2.wav, ..., etc). Script attempt to match note and velocity with the additionnal 
possibility to provide the naming pattern ( ex : 'Moog_{note}.wav' or guitar_{note}_v{vel}.wav  )


## Options 

```
options:
  -h, --help            show this help message and exit
  --folder FOLDER       Folder containing samples
  --samples SAMPLES [SAMPLES ...]
                        List of sample files
  --out OUT             Output .dspreset path OR output directory. Default: sample folder.
  --pattern PATTERN     Explicit pattern, e.g. 'piano_{note}_vel{vel}' (no extension).
  --middle-c MIDDLE_C   Define C{N} = 60. Default: 4 (C4=60).
  --copy-samples        Copy samples next to preset under Samples/ for portability.
  --on-duplicate {error,keep-first,keep-last}
  --low-spread LOW_SPREAD
                        Limit extension below lowest root (in semitones).
  --high-spread HIGH_SPREAD
                        Limit extension above highest root (in semitones).
```

## usage

### Basic use
```
python decent_preset_gen.py --folder ./FM_Bass/ 
```

### Make preset "portable" (independant from absolute path)
```
python decent_preset_gen.py --folder ./FM_Bass/ --out ./decent_bass --copy-sample
```

###  portable Use + pattern use
```
python decent_preset_gen.py 
    --folder ./FM_Bass/ \
    --out ./decent_bass \
    --pattern 'FM Bass {note}.wav' \ 
    --copy-sample
```
