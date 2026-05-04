# extract_formants.praat
# Headless formant extraction for vowel intervals in a TextGrid.
#
# Run from the command line via Praat --run:
#
#   praat --run extract_formants.praat <audio> <textgrid> <words_tier> \
#         <phones_tier> <vowel_list_file> <max_formant_hz> <output_tsv>
#
# Arguments:
#   audio           - audio file (any format Praat reads)
#   textgrid        - aligned TextGrid (must contain words_tier and phones_tier)
#   words_tier      - name of the word-level tier (e.g. "words", "spk1 - words")
#   phones_tier     - name of the phone-level tier (e.g. "phones", "spk1 - phones")
#   vowel_list_file - newline-delimited list of vowel symbols (no stress digits).
#                     Phones whose label (with stress digits stripped) appears
#                     in this list are treated as vowels.
#   max_formant_hz  - upper bound for formant tracking (5000 for low/male
#                     voices, 5500 for high/female; pass as integer).
#   output_tsv      - path to write the per-(vowel, timepoint) TSV.
#
# Output TSV columns (tab-separated, one row per vowel x timepoint):
#   vowel_label  start  end  measurement_point_pct
#   F1  F2  F3  B1  B2  B3
#   word  preceding_phone  following_phone
#
# Empty cells are written as "" (not "NA") so the Python post-processor can
# distinguish missing values from genuine zeros.

form Args
    sentence Audio
    sentence Textgrid
    sentence Words_tier
    sentence Phones_tier
    sentence Vowel_list_file
    integer Max_formant_hz 5000
    sentence Output_tsv
endform

# --- Read vowel list into a string we can search ---
# Format: each line wrapped with newline$ on either side, so we can do a
# substring match for "<newline>VOWEL<newline>" without partial-prefix matches.
vowels$ = newline$
vowelStream$ = readFile$: vowel_list_file$
nLines = length(vowelStream$)
i = 1
buf$ = ""
while i <= nLines
    ch$ = mid$(vowelStream$, i, 1)
    if ch$ = newline$
        if length(buf$) > 0
            vowels$ = vowels$ + buf$ + newline$
        endif
        buf$ = ""
    else
        buf$ = buf$ + ch$
    endif
    i = i + 1
endwhile
if length(buf$) > 0
    vowels$ = vowels$ + buf$ + newline$
endif

# --- Open Sound and TextGrid ---
sound = Read from file: audio$
soundId = selected("Sound")
tg = Read from file: textgrid$
tgId = selected("TextGrid")

# --- Locate the tiers by name ---
selectObject: tgId
nTiers = Get number of tiers
wordsTierNum = 0
phonesTierNum = 0
for t to nTiers
    tierName$ = Get tier name: t
    if tierName$ = words_tier$
        wordsTierNum = t
    endif
    if tierName$ = phones_tier$
        phonesTierNum = t
    endif
endfor
if wordsTierNum = 0 or phonesTierNum = 0
    exitScript: "Tier(s) not found. Wanted words='" + words_tier$ + "', phones='" + phones_tier$ + "'."
endif

# --- Compute formant track once over the whole sound ---
selectObject: soundId
To Formant (burg): 0, 5, max_formant_hz, 0.025, 50
formantId = selected("Formant")

# --- Open output TSV and write header ---
deleteFile: output_tsv$
header$ = "vowel_label" + tab$ + "start" + tab$ + "end" + tab$
    ... + "measurement_point_pct" + tab$
    ... + "F1" + tab$ + "F2" + tab$ + "F3" + tab$
    ... + "B1" + tab$ + "B2" + tab$ + "B3" + tab$
    ... + "word" + tab$ + "preceding_phone" + tab$ + "following_phone"
appendFileLine: output_tsv$, header$

# --- Iterate phones tier ---
selectObject: tgId
nPhones = Get number of intervals: phonesTierNum

# Five measurement points
pcts# = {20, 35, 50, 65, 80}

for p to nPhones
    selectObject: tgId
    label$ = Get label of interval: phonesTierNum, p
    label$ = replace_regex$ (label$, "^\s+", "", 0)
    label$ = replace_regex$ (label$, "\s+$", "", 0)
    if length(label$) = 0
        goto skip
    endif
    # Strip ARPA stress digit (single trailing 0/1/2) for vowel-set lookup.
    # Applied unconditionally — safe for v1 because:
    #  - ARPA labels (FAVE/MFA) end in 0/1/2 (e.g. AA1, IH0): strip is needed.
    #  - X-SAMPA labels in BAS WebMAUS eng-US output don't end in 0/1/2:
    #    no-op.
    # For v2 (other WebMAUS languages where X-SAMPA stress digits do
    # appear), the wrapper should pass phoneset and gate this strip on
    # phoneset == "arpa".
    bare$ = replace_regex$ (label$, "([0-2])$", "", 0)
    # Substring match: vowels$ contains "<newline>BARE<newline>"
    if index(vowels$, newline$ + bare$ + newline$) = 0
        goto skip
    endif
    # This phone is a vowel
    vStart = Get start time of interval: phonesTierNum, p
    vEnd   = Get end time of interval: phonesTierNum, p

    # Preceding / following phones (literal labels of adjacent non-empty intervals)
    prev$ = ""
    for q from p - 1 to 1
        cand$ = Get label of interval: phonesTierNum, q
        cand$ = replace_regex$ (cand$, "^\s+", "", 0)
        cand$ = replace_regex$ (cand$, "\s+$", "", 0)
        if length(cand$) > 0
            prev$ = cand$
            q = 0
        endif
    endfor
    foll$ = ""
    for q from p + 1 to nPhones
        cand$ = Get label of interval: phonesTierNum, q
        cand$ = replace_regex$ (cand$, "^\s+", "", 0)
        cand$ = replace_regex$ (cand$, "\s+$", "", 0)
        if length(cand$) > 0
            foll$ = cand$
            q = nPhones + 1
        endif
    endfor

    # Containing word: word interval whose start <= mid < end
    midT = (vStart + vEnd) / 2
    word$ = ""
    nWords = Get number of intervals: wordsTierNum
    for w to nWords
        wStart = Get start time of interval: wordsTierNum, w
        wEnd   = Get end time of interval: wordsTierNum, w
        if wStart <= midT and midT < wEnd
            word$ = Get label of interval: wordsTierNum, w
            word$ = replace_regex$ (word$, "^\s+", "", 0)
            word$ = replace_regex$ (word$, "\s+$", "", 0)
            w = nWords + 1
        endif
    endfor

    # --- Frame-center-bounded measurement points ---
    selectObject: formantId
    # Get the indices of the first and last formant frames falling inside
    # [vStart, vEnd] so 20% and 80% don't fall outside frame coverage.
    nFrames = Get number of frames
    firstFrame = 0
    lastFrame  = 0
    for f to nFrames
        ft = Get time from frame number: f
        if ft >= vStart and firstFrame = 0
            firstFrame = f
        endif
        if ft <= vEnd
            lastFrame = f
        endif
    endfor
    if firstFrame = 0 or lastFrame = 0 or firstFrame > lastFrame
        # No formant frames inside the vowel; emit empty rows so the row count
        # per vowel stays constant at 5.
        for k to 5
            row$ = label$ + tab$ + fixed$(vStart, 4) + tab$ + fixed$(vEnd, 4) + tab$
                ... + string$(pcts#[k]) + tab$ + tab$ + tab$ + tab$ + tab$ + tab$
                ... + word$ + tab$ + prev$ + tab$ + foll$
            appendFileLine: output_tsv$, row$
        endfor
        goto skip
    endif

    tFirst = Get time from frame number: firstFrame
    tLast  = Get time from frame number: lastFrame
    innerDur = tLast - tFirst

    for k to 5
        pct = pcts#[k]
        tPt = tFirst + (pct / 100) * innerDur
        f1 = Get value at time: 1, tPt, "hertz", "Linear"
        f2 = Get value at time: 2, tPt, "hertz", "Linear"
        f3 = Get value at time: 3, tPt, "hertz", "Linear"
        b1 = Get bandwidth at time: 1, tPt, "hertz", "Linear"
        b2 = Get bandwidth at time: 2, tPt, "hertz", "Linear"
        b3 = Get bandwidth at time: 3, tPt, "hertz", "Linear"

        f1$ = if f1 = undefined then "" else fixed$(f1, 1) fi
        f2$ = if f2 = undefined then "" else fixed$(f2, 1) fi
        f3$ = if f3 = undefined then "" else fixed$(f3, 1) fi
        b1$ = if b1 = undefined then "" else fixed$(b1, 1) fi
        b2$ = if b2 = undefined then "" else fixed$(b2, 1) fi
        b3$ = if b3 = undefined then "" else fixed$(b3, 1) fi

        row$ = label$ + tab$ + fixed$(vStart, 4) + tab$ + fixed$(vEnd, 4) + tab$
            ... + string$(pct) + tab$
            ... + f1$ + tab$ + f2$ + tab$ + f3$ + tab$
            ... + b1$ + tab$ + b2$ + tab$ + b3$ + tab$
            ... + word$ + tab$ + prev$ + tab$ + foll$
        appendFileLine: output_tsv$, row$
    endfor

    label skip
endfor

# --- Cleanup ---
removeObject: formantId
removeObject: tgId
removeObject: soundId
