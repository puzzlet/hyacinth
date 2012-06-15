#!/usr/bin/env python
# requires 2.7 +

import argparse
import itertools
import os.path
import re
import subprocess
import sys

import music21

VOWELS = [
    b'a',
    b'a:',
    b'aI',
    b'aU',
    b'e',
    b'e:',
    b'E',
    b'i',
    b'i:',
    b'I',
    b'?I',
    b'o',
    b'O',
    b'OY',
    b'u',
    b'u:',
    b'U',
    b'?U',
    b'M',
    b'V',
    b'@',
    b'@U',
    b'3:',
    b'6',
    b'{',

    b'r=',
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('lang', metavar='voice', type=str,
        help="MBROLA voice name (e.g. en1)")
    parser.add_argument('file', metavar='score', type=str,
        help="Path to the score (MusicXML)")
    parser.add_argument('--pho', action='store_true',
        help="Print pho to stdout")
    args = parser.parse_args()

    music21_conf = music21.environment.UserSettings()
    if music21_conf['warnings'] in ['yes', 'y', '1', 'true']:
        sys.stderr.write("Suppressing music21 warnings.\n")
        music21_conf['warnings'] = False

    score = music21.converter.parse(open(args.file).read())
    # XXX assumes single part
    buf = []
    # (0, 2) - (1, 3)
    # Note 0 to 2 respond syllable 1 to 3
    # note -> list of syllable(s)
    lyric_list = []
    note_to_lyric = {}

    chunks = [{'notes': []}]
    for obj in score.flat:
        if isinstance(obj, music21.note.Rest):
            chunks.append({'notes': [obj]})
            continue
        if not isinstance(obj, music21.note.Note):
            continue
        # TODO find music21 to midi
        # repeat, dal segno etc.
        if obj.lyrics:
            # XXX assuming single verse
            lyric = obj.lyrics[0]
            chunks.append({'notes': [obj], 'lyric': lyric,
                'syllables': [lyric.text]})
            text = lyric.text
            if lyric.syllabic == 'begin':
                text = ' ' + text
            elif lyric.syllabic == 'end':
                text = text + ' '
            elif lyric.syllabic == 'single':
                text = ' ' + text + ' '
            buf.append(text)
        elif 'lyric' in chunks[-1]: # and chunks[-1]['lyric'].extend:
            chunks[-1]['notes'].append(obj)
        else:
            chunks.append({'notes': [obj]})
            continue
    text = ''.join(buf)

    stdout, stderr = subprocess.Popen(['espeak',
        '-v', 'mb-{}'.format(args.lang),
        '-q', '--pho',
        text
    ], stdout=subprocess.PIPE).communicate()
    lines = stdout.split(b'\n')
    syllables = [[]]
    was_vowel = False
    for i, line in enumerate(lines):
        if not line:
            continue
        tokens = line.split()
        if tokens[0] == '_':
            syllables.append([])
            continue
        is_vowel = tokens[0] in VOWELS
        if was_vowel: # and not is_vowel:
            syllables.append([])
        syllables[-1].append(tokens)
        was_vowel = is_vowel
    buf = []
    i = 0
    for chunk in chunks:
        if 'syllables' not in chunk:
            continue
        n = len(chunk['syllables'])
        chunk['pho'] = list(itertools.chain(*syllables[i:i+n]))
        i += n
    for chunk in chunks:
        try:
            durations = [_.seconds for _ in chunk['notes']]
            # duration in milliseconds
        except music21.base.Music21ObjectException: 
            # File "music21/base.py", line 4134, in _getSeconds
            #     raise Music21ObjectException('this object does not have a TempoIndication in DefinedContexts')
            # music21.base.Music21ObjectException: this object does not have a TempoIndication in DefinedContexts
            bpm = 120
            durations = [
                _.duration.quarterLength * (60000./bpm) for _ in chunk['notes']]
        if all(isinstance(_, music21.note.Rest) for _ in chunk['notes']):
            buf.append(b'_ {}'.format(sum(durations)))
            continue
        total_duration = sum(durations)
        if 'lyric' not in chunk:
            for i, note in enumerate(chunk['notes']):
                f0 = note.frequency # TODO: temperament
                buf.append(b'A {dur} 0 {freq} 100 {freq}'.format(
                    dur=durations[i],
                    freq=f0,
                ))
            continue
        buf.append(b' '.join([b';',
            b'{}'.format(total_duration),
            u' '.join(chunk['syllables']).encode('utf8'),
        ]))
        dt = [float(_[1]) for _ in chunk['pho']]
        x = sum(dt)
        if x <= total_duration:
            vowel_index = [i for (i, _) in enumerate(chunk['pho']) \
                if _[0] in VOWELS]
            if vowel_index:
                dt[vowel_index[-1]] += total_duration - x
        else:
            dt = [_/x*total_duration for _ in dt]
        for k, tokens in enumerate(chunk['pho']):
            pho_start = sum(dt[:k])
            pho_end = pho_start + dt[k]
            for i, note in enumerate(chunk['notes']):
                f0 = note.frequency # TODO: temperament
                note_start = sum(durations[:i])
                note_end = note_start + durations[i]
                if note_start > pho_end:
                    break
                if note_end < pho_start:
                    continue
                l = dt[k]
                if note_start > pho_start:
                    l -= (note_start - pho_start)
                    # XXX
                    tokens[0] = re.findall(
                        r'[a-zA-Z{3@]:?',
                        tokens[0])[-1]
                if note_end < pho_end:
                    l -= (pho_end - note_end)
                contour = [map(float, tokens[_:_+2]) for _ in range(2, len(tokens), 2)]
                contour = [(_t, _f*f0/contour[-1][1]) for (_t, _f) in contour]
                buf.append(b' '.join([
                    tokens[0],
                    b'{}'.format(l),
                    b' '.join(b'{} {}'.format(*_) for _ in contour),
                ]))
    buf = b'\n'.join(buf)
    if args.pho:
        print buf
    subprocess.Popen(['mbrola',
        mbrola_voice_path(args.lang),
        '-',
        'test.wav'
    ], stdin=subprocess.PIPE).communicate(input=buf)

def mbrola_voice_path(keyword):
    assert '..' not in keyword
    for candidate in [
        os.path.join(os.path.expanduser('~'), 'mbrola', keyword),
        os.path.join(os.path.expanduser('~'), 'mbrola', keyword, keyword),
        os.path.join('/usr/share/mbrola', keyword),
        os.path.join('/usr/share/mbrola', keyword, keyword),
        os.path.join('/usr/share/mbrola/voices', keyword),
    ]:
        if os.path.isfile(candidate):
            return candidate

if __name__ == '__main__':
    main()

