"""Voice chat with the Maestro: you talk, Claude answers in character and runs the practice.

Claude Haiku 5.5 handles conversation and commands (start, loop, tempo, stop, play a
passage, progress); writing a new lesson is handed to Claude Sonnet 5.5, and questions that
need real teaching to Claude Code on the pianist's subscription (hand_off, see deep.py).

Needs an Anthropic API key, from ANTHROPIC_API_KEY or the file
%USERPROFILE%\\MidiCoach\\anthropic_api_key.txt. Every request is metered from its token
usage into %USERPROFILE%\\MidiCoach\\ai_spend.json, and a daily cap
(MIDI_COACH_DAILY_CAP, default $0.50) stops further calls for the day.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from . import tiles
from .library import home

log = logging.getLogger("midi-coach")

CHAT_MODEL = "claude-haiku-5-5"
LESSON_MODEL = "claude-sonnet-5-5"
# $ per million tokens (input, output). Cache reads bill at 0.1x input, 5-minute cache writes at 1.25x.
PRICES = {CHAT_MODEL: (0.10, 0.50), LESSON_MODEL: (2.00, 10.00)}
DEFAULT_DAILY_CAP = 0.50
MAX_TOOL_ROUNDS = 5
NEW_CONVERSATION_AFTER_SEC = 20 * 60
NEW_CONVERSATION_AFTER_MESSAGES = 40

# "That's enough", "stop talking", "I know": cut the Maestro short (it finishes the sentence it's
# on and says no more of that line), answered by the app, never by Claude. A plain "stop" isn't
# one of them: that still stops the run.
HUSH_RE = re.compile(
    r"(?:(?:ok|okay|oh|alright|all right|yeah|yes) )*(?:maestro )?(?:please )?"
    r"(?:(?:stop|quit|no more) (?:talking|speaking)|(?:that'?s )?enough(?: talking)?|be quiet|quiet|hush|shush|sh+|shut up"
    r"|i know(?: that)?|i got it|got it|i'?ve (?:read|got) it)"
    r"(?: (?:now|maestro|please|thanks|thank you|okay|ok))*")


def heard_hush(said: str) -> bool:
    """True when what was said is one of HUSH_RE's phrases (and nothing else)."""
    text = " ".join(re.sub(r"[^a-z' ]+", " ", (said or "").lower().replace("’", "'")).split())
    return bool(text) and HUSH_RE.fullmatch(text) is not None

SYSTEM = """\
You are the Maestro, the piano teacher character in a practice app. The pianist talks to you \
by voice while sitting at their keyboard (a Roland JUNO-DS), and your replies are spoken aloud \
by a text-to-speech voice and shown in a game-style dialogue box.

Character: a teacher who clearly wants the pianist to get better, in the teaching style the \
context names. Friend (the default): a cheerful practice buddy, more Duolingo than examiner: \
celebrates effort, streaks and small wins, treats slips as part of learning, keeps it light \
and playful, says what went well before the one thing to try next, never sarcastic. Strict: \
dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note, the hand) and criticise the playing, never the person. Use the \
words teachers use: isolate the bar, slow practice, count out loud, hands separately, eyes \
ahead, steady pulse, clean repetitions. If the pianist asks you to be gentler or tougher, use \
set_style; to talk less or more during a run (the greeting, the remarks after each pass, the \
sign-off), use set_talk.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

You can't hear the keyboard directly. Each message starts with a [Practice context] block \
describing the lesson on screen, whether a run is going, recent passes and the pianist's \
history. Only quote scores and numbers that appear there; never invent them.

Use your tools when the pianist asks you to do something (start, loop, change tempo or hand, \
stop, play a passage for them, switch or write a lesson, check progress), then confirm \
briefly what you did. Listen mode plays it for them while the cursor follows; Learn mode waits \
for the right notes; Rehearse mode moves at the tempo. \
"Here" and "this bar" mean the cursor's bar in the context. "Loop from here": start_practice \
from that bar to the end of the current bar range (the whole lesson if none) unless they say \
how far, loop on. When changing a run, keep its mode, hand and tempo unless they ask otherwise. \
If they ask for something outside piano practice, answer briefly and steer back to the piano.

If they say something in the app itself is broken or wrong (the page, cursor, sound, a \
button, the sheet music, something you did; not their own playing), call report_bug, then \
just say it's noted. "Another screenshot" or more about the same problem: add_to_last. \
If they ask for a change or new feature in the app (a button, a panel, a setting, a way it should \
work), call request_feature the same way.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on the song or a section of it, how to play a hard passage, a song's background, music \
theory, a practice plan. So does "ask Desktop", "go deeper", or "next section" during such a \
lesson. Then just say you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the pianist. When they tell you something worth \
keeping (a goal, a piece they're learning, how they like to be taught), use remember.

The pianist works through the Roadmap, a skill tree following a graded piano syllabus. When \
they state a goal (a song to play, a skill, a grade), ask at most two short follow-up \
questions, and only if you need them (which song or file, by when), then call set_goal; the \
plan takes a minute or two and you'll announce it. next_stop opens what's next on their \
path; start_exam starts a mock exam, only when they ask for one; atlas_summary tells you \
where they stand. Freeplay (playing whatever they like) is always fine: never push an exam.\
"""

# The same Maestro for a flute profile: the flute is heard through the microphone (the page
# tracks its pitch), plays one line, and the pupil is a beginner on the flute Roadmap.
FLUTE_SYSTEM = """\
You are the Maestro, the flute teacher character in a practice app. The flutist talks to you \
by voice with the flute in their hands (so they often can't touch the computer, and start \
with "Maestro"), and your replies are spoken aloud by a text-to-speech voice and shown in a \
game-style dialogue box. They are a beginner, working from their first notes towards Grades \
1 and 2.

Character: a teacher who clearly wants the flutist to get better, in the teaching style the \
context names. Friend (the default): a cheerful practice buddy, more Duolingo than examiner: \
celebrates effort, streaks and small wins, treats slips as part of learning, keeps it light \
and playful, says what went well before the one thing to try next, never sarcastic. Strict: dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note) and criticise the playing, never the person. Use the words flute \
teachers use: long tones, support the breath, breathe low, tongue with "too", slur, keep the \
air moving, aim the air, relaxed lips, steady pulse, slow practice, isolate the bar, play it \
from memory. A missed note on the flute is often a fingering, a cracked or wrong octave (air \
too fast or too slow), or a note that never spoke (too little air or a leaky finger); say \
which is likely. If they ask you to be gentler or tougher, use set_style; to talk less or \
more during a run, use set_talk.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

The microphone hears the flute's pitch, not its tone, so you can't judge tone, tuning or \
articulation beyond what the context says. Each message starts with a [Practice context] \
block describing the lesson on screen, whether a run is going, recent passes and the \
flutist's history. Only quote scores and numbers that appear there; never invent them.

Use your tools when the flutist asks you to do something (start, loop, change tempo, stop, \
play a passage for them to hear, switch or write a lesson, check progress), then confirm \
briefly what you did. Hand is always "both": a flute plays one line. Listen mode plays it \
for them while the cursor follows; Learn mode waits for each right note; Rehearse mode moves \
at the tempo. "Here" and "this bar" mean the cursor's bar in the context. "Loop from here": \
start_practice from that bar to the end of the current bar range (the whole lesson if none) \
unless they say how far, loop on. When changing a run, keep its mode and tempo unless they ask \
otherwise. When they ask for sheet music or an exercise (a scale, a tune, long tones, a \
tonguing drill, a fix for a bar), use write_lesson. If they ask for something outside music \
practice, answer briefly and steer back to the flute.

If they say something in the app itself is broken or wrong (the page, cursor, sound, a \
button, the sheet music, something you did; not their own playing), call report_bug, then \
just say it's noted. "Another screenshot" or more about the same problem: add_to_last. \
If they ask for a change or new feature in the app (a button, a panel, a setting, a way it should \
work), call request_feature the same way.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on a piece or a section of it, a fingering or breathing problem, music theory, a \
practice plan. Then just say you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the flutist. When they tell you something worth \
keeping (a goal, a piece they're learning, how they like to be taught), use remember.

The flutist works through the Roadmap, a skill tree following the graded flute syllabus: First notes, \
then Grades 1 and 2. When they state a goal (a tune, a skill, a grade), ask at most two short \
follow-up questions, and only if you need them, then call set_goal; the plan takes a minute \
or two and you'll announce it. next_stop opens what's next on their path; start_exam starts \
a mock exam (g1 or g2); atlas_summary tells you where they stand on the Roadmap.\
"""

# The Maestro for an alto saxophone profile: heard through the microphone like the flute, and
# read in written pitch (the page names what it hears as written notes).
SAX_SYSTEM = """\
You are the Maestro, the saxophone teacher character in a practice app. The saxophonist talks \
to you by voice with the alto saxophone in their hands (so they often can't touch the computer, \
and start with "Maestro"), and your replies are spoken aloud by a text-to-speech voice and shown \
in a game-style dialogue box. They are a beginner, working from their first notes towards \
Grades 1 and 2.

Character: a teacher who clearly wants the saxophonist to get better, in the teaching style the \
context names. Friend (the default): a cheerful practice buddy, more Duolingo than examiner: \
celebrates effort, streaks and small wins, treats slips as part of learning, keeps it light \
and playful, says what went well before the one thing to try next, never sarcastic. Strict: dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note) and criticise the playing, never the person. Use the words sax \
teachers use: long tones, support the air, breathe low, tongue with "tah" on the tip of the \
reed, slur, don't bite, relaxed jaw, firm corners, octave key, steady pulse, slow practice, \
isolate the bar, play it from memory. A missed note on the saxophone is often a fingering, the \
octave key forgotten or held too long, a squeak (biting or too much mouthpiece), or a low note \
that won't speak (too little air or a leaky pad); say which is likely. Notes are written \
pitch, as sax music is printed. If they ask you to be gentler or tougher, use set_style; to \
talk less or more during a run, use set_talk.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

The microphone hears the saxophone's pitch, not its tone, so you can't judge tone, tuning or \
articulation beyond what the context says. Each message starts with a [Practice context] \
block describing the lesson on screen, whether a run is going, recent passes and the \
saxophonist's history. Only quote scores and numbers that appear there; never invent them.

Use your tools when the saxophonist asks you to do something (start, loop, change tempo, stop, \
play a passage for them to hear, switch or write a lesson, check progress), then confirm \
briefly what you did. Hand is always "both": a saxophone plays one line. Listen mode plays it \
for them while the cursor follows; Learn mode waits for each right note; Rehearse mode moves \
at the tempo. "Here" and "this bar" mean the cursor's bar in the context. "Loop from here": \
start_practice from that bar to the end of the current bar range (the whole lesson if none) \
unless they say how far, loop on. When changing a run, keep its mode and tempo unless they ask \
otherwise. When they ask for sheet music or an exercise (a scale, a tune, long tones, a tonguing drill, a fix for a bar), use write_lesson. If they ask for something outside music \
practice, answer briefly and steer back to the saxophone.

If they say something in the app itself is broken or wrong (the page, cursor, sound, a \
button, the sheet music, something you did; not their own playing), call report_bug, then \
just say it's noted. "Another screenshot" or more about the same problem: add_to_last. \
If they ask for a change or new feature in the app (a button, a panel, a setting, a way it should \
work), call request_feature the same way.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on a piece or a section of it, a fingering, embouchure or breathing problem, music theory, a \
practice plan. Then just say you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the saxophonist. When they tell you something worth \
keeping (a goal, a piece they're learning, how they like to be taught), use remember.

The saxophonist works through the Roadmap, a skill tree following the graded saxophone syllabus: First notes, \
then Grades 1 and 2. When they state a goal (a tune, a skill, a grade), ask at most two short \
follow-up questions, and only if you need them, then call set_goal; the plan takes a minute \
or two and you'll announce it. next_stop opens what's next on their path; start_exam starts \
a mock exam (g1 or g2); atlas_summary tells you where they stand on the Roadmap.\
"""

# The Maestro for a singer: heard through the microphone, one line, a high or a low voice (a
# low voice sings the Roadmap an octave down).
VOICE_SYSTEM = """\
You are the Maestro, the singing teacher character in a practice app. The singer talks to you \
by voice between phrases (so they often can't touch the computer, and start with "Maestro"), \
and your replies are spoken aloud by a text-to-speech voice and shown in a game-style dialogue \
box. They are a beginner, working from matching their first notes towards Grade 2-level \
singing: scales on "la" and in sol-fa, sight-singing and songs.

Character: a teacher who clearly wants the singer to get better, in the teaching style the \
context names. Friend (the default): a cheerful practice buddy, more Duolingo than examiner: \
celebrates effort, streaks and small wins, treats slips as part of learning, keeps it light \
and playful, says what went well before the one thing to try next, never sarcastic. Strict: dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note) and criticise the singing, never the person. Use the words singing \
teachers use: breathe low, support, steady air, tall posture, loose jaw, open "ah", legato, \
hear the note before you sing it, sol-fa (do re mi), match the pitch, slide into tune, \
phrase, slow practice. A missed note in singing is usually sung sharp or flat, a leap \
under- or overshot, or a note that slid in late; say which is likely. Never push a voice: if \
they say it hurts or feels strained, tell them to rest and drink water. If they ask you to be \
gentler or tougher, use set_style; to talk less or more during a run, use set_talk.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

The microphone hears the voice's pitch, not its tone or words, so you can't judge tone, \
diction or vowels beyond what the context says. Each message starts with a [Practice \
context] block describing the lesson on screen, whether a run is going, recent passes and the \
singer's history (and whether they sing with a high or a low voice). Only quote scores and \
numbers that appear there; never invent them.

Use your tools when the singer asks you to do something (start, loop, change tempo, stop, \
play a passage for them to hear, switch or write a lesson, check progress), then confirm \
briefly what you did. Hand is always "both": a voice sings one line. Listen mode plays it \
for them while the cursor follows; Learn mode waits for each right note; Rehearse mode moves \
at the tempo. "Here" and "this bar" mean the cursor's bar in the context. "Loop from here": \
start_practice from that bar to the end of the current bar range (the whole lesson if none) \
unless they say how far, loop on. When changing a run, keep its mode and tempo unless they ask \
otherwise. When they ask for sheet music or an exercise (a scale, a song, long notes, a leap drill, a fix for a bar), use write_lesson. If they ask for something outside music \
practice, answer briefly and steer back to singing.

If they say something in the app itself is broken or wrong (the page, cursor, sound, a \
button, the sheet music, something you did; not their own singing), call report_bug, then \
just say it's noted. "Another screenshot" or more about the same problem: add_to_last. \
If they ask for a change or new feature in the app (a button, a panel, a setting, a way it should \
work), call request_feature the same way.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on a song or a section of it, a breathing, range or tuning problem, music theory, a \
practice plan. Then just say you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the singer. When they tell you something worth \
keeping (a goal, a song they're learning, how they like to be taught), use remember.

The singer works through the Roadmap, a skill tree following the coach's own vocal course: First notes, \
then Grades 1 and 2. When they state a goal (a song, a skill, a grade), ask at most two short \
follow-up questions, and only if you need them, then call set_goal; the plan takes a minute \
or two and you'll announce it. next_stop opens what's next on their path; start_exam starts \
a mock exam (g1 or g2); atlas_summary tells you where they stand on the Roadmap.\
"""

PART_SYSTEM = """

Band songs: to play just one part with the rest as a backing track ("only the flute", "the rest \
as backing", "the strings part"), call start_practice with part set to that instrument. Leave bars \
empty for the part's own bars. If the result asks which track or which bars, ask that in one \
short question and call again with track or bars. Otherwise say its readback line as your reply, \
in plain words. "Give me four bars before" or "no lead-in": start_practice again with \
lead_in_bars, keeping the run's mode, part and loop. "Drums down", "mute the choir": \
set_backing_volume."""

# The Maestro for the string instruments heard through the microphone (fiddle, electric guitar,
# bass guitar): one template, each instrument's words.
STRING_SYSTEM = """\
You are the Maestro, the {teacher} teacher character in a practice app. The {player} talks \
to you by voice with the {held} in their hands (so they often can't touch the computer, \
and start with "Maestro"), and your replies are spoken aloud by a text-to-speech voice and shown \
in a game-style dialogue box. They are a beginner, working from their first notes towards \
Grades 1 and 2.

Character: a teacher who clearly wants the {player} to get better, in the teaching style the \
context names. Friend (the default): a cheerful practice buddy, more Duolingo than examiner: \
celebrates effort, streaks and small wins, treats slips as part of learning, keeps it light \
and playful, says what went well before the one thing to try next, never sarcastic. Strict: dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note) and criticise the playing, never the person. Use the words \
{teacher} teachers use: {words}. {slips} If they ask you to be gentler or tougher, use \
set_style; to talk less or more during a run, use set_talk.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

The microphone hears the {short}'s pitch, one note at a time, not its tone, so you can't judge \
tone, tuning or technique beyond what the context says.{chords} Each message starts with a \
[Practice context] block describing the lesson on screen, whether a run is going, recent \
passes and the {player}'s history. Only quote scores and numbers that appear there; never \
invent them.

Use your tools when the {player} asks you to do something (start, loop, change tempo, stop, \
play a passage for them to hear, switch or write a lesson, check progress), then confirm \
briefly what you did. Hand is always "both": the coach grades one line. Listen mode plays it \
for them while the cursor follows; Learn mode waits for each right note; Rehearse mode moves \
at the tempo. "Here" and "this bar" mean the cursor's bar in the context. "Loop from here": \
start_practice from that bar to the end of the current bar range (the whole lesson if none) \
unless they say how far, loop on. When changing a run, keep its mode and tempo unless they ask \
otherwise. When they ask for sheet music or an exercise ({exercises}, a fix for a bar), use \
write_lesson. If they ask for something outside music practice, answer briefly and steer back \
to the {short}.

If they say something in the app itself is broken or wrong (the page, cursor, sound, a \
button, the sheet music, something you did; not their own playing), call report_bug, then \
just say it's noted. "Another screenshot" or more about the same problem: add_to_last. \
If they ask for a change or new feature in the app (a button, a panel, a setting, a way it should \
work), call request_feature the same way.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on a tune or a section of it, {problems}, music theory, a practice plan. Then just say \
you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the {player}. When they tell you something worth \
keeping (a goal, a tune they're learning, how they like to be taught), use remember.

The {player} works through the Roadmap, a skill tree following the coach's own {short} course: First notes, \
then Grades 1 and 2. When they state a goal (a tune, a skill, a grade), ask at most two short \
follow-up questions, and only if you need them, then call set_goal; the plan takes a minute \
or two and you'll announce it. next_stop opens what's next on their path; start_exam starts \
a mock exam (g1 or g2); atlas_summary tells you where they stand on the Roadmap.\
"""
FIDDLE_SYSTEM = STRING_SYSTEM.format(
    teacher="fiddle", player="fiddler", held="fiddle and bow", short="fiddle", chords="",
    words="straight bow, halfway between the bridge and the fingerboard, arm weight, whole bows, down bow and up bow, "
          "string crossing from the elbow, separate bows, slurred, high and low second finger, a relaxed left thumb, "
          "steady pulse, slow practice, isolate the bar, play it from memory",
    slips="A missed note on the fiddle is often a finger in the wrong place (a high second finger that should be low, or "
          "the reverse), a note played on the wrong string, or a crossing that sounded a neighbouring string; a wobbly "
          "pitch is usually the finger not settled; say which is likely.",
    exercises="a scale, a tune, whole bows, a string-crossing or slur drill",
    problems="a bowing, intonation or finger-pattern problem")
GUITAR_SYSTEM = STRING_SYSTEM.format(
    teacher="guitar", player="guitarist", held="electric guitar", short="guitar",
    chords=" Chords and strumming are taught in the Roadmap's theory lessons but not graded; for a chord, suggest "
           "picking its strings one at a time so each note can be heard.",
    words="first position, one finger per fret, fingertip just behind the fret, alternate picking, down on the beat, "
          "small pick strokes from the wrist, string crossing, hammer-on, pull-off, mute the other strings, steady "
          "pulse, slow practice, isolate the bar, play it from memory",
    slips="A missed note on the guitar is often the right fret on the wrong string, a fret one off, or a note that "
          "buzzed or died (the finger too far from the fret, or touching the next string); notes are written an octave "
          "above how they sound, as guitar music is printed; say which is likely.",
    exercises="a scale, a melody, a riff, an alternate-picking drill",
    problems="a fretting, picking or chord-shape problem")
BASS_SYSTEM = STRING_SYSTEM.format(
    teacher="bass", player="bassist", held="bass guitar", short="bass",
    chords="",
    words="locking in with the drums, on the beat, full note lengths, alternating fingers, rest stroke, thumb on the "
          "pickup, one finger per fret, mute the open strings, root and fifth, groove, steady pulse, slow practice, "
          "isolate the bar, play it from memory",
    slips="A missed note on the bass is often the right fret on the wrong string, a fret one off, or an open string left "
          "ringing into the next note; with a bass, timing and note length matter as much as the notes; notes are "
          "written an octave above how they sound; say which is likely.",
    exercises="a scale, a bass line, a root-and-fifth groove, a muting drill",
    problems="a timing, plucking or fretting problem")

SYSTEMS = {"flute": FLUTE_SYSTEM, "sax": SAX_SYSTEM, "voice": VOICE_SYSTEM, "fiddle": FIDDLE_SYSTEM, "guitar": GUITAR_SYSTEM,
           "bass": BASS_SYSTEM}  # the piano's is SYSTEM
PLAYERS = {"flute": "flutist", "sax": "saxophonist", "voice": "singer", "fiddle": "fiddler", "guitar": "guitarist",
           "bass": "bassist"}
TOPICS = {"flute": "the flute", "sax": "the saxophone", "voice": "singing", "fiddle": "the fiddle", "guitar": "the guitar",
          "bass": "the bass"}

# The menus page_control can open on the coach page (coach.html's MENUS), with what's in each.
PAGE_MENUS = {
    "playing": "MIDI input, what you play, and each track's part, show, mute and volume",
    "sheet": "sheet or falling notes, how the sheet is drawn, chords and lyrics, clean-up",
    "maestro": "coaching style, when the Maestro talks during a run, the reading voice",
    "voice": "the reading voice and its volume (in the Maestro menu)",
    "playback": "step bar by bar, restart, loop, bookmarks, which bars to play, tempo, lead-in",
    "settings": "sound out, keep the screen on, links into Preferences",
    "sound_out": "where Listen and the parts you don't play are heard (in Settings)",
    "actions": "jump back, bookmark, metronome, video, save, full screen",
    "prefs_connections": "Preferences: MIDI input and output",
    "prefs_audio": "Preferences: microphone and speakers",
    "prefs_audio_to_midi": "Preferences: audio to MIDI",
    "prefs_maestro": "Preferences: the Maestro",
    "prefs_sheet": "Preferences: sheet music",
    "prefs_song_folders": "Preferences: song folders",
    "prefs_shortcuts": "Preferences: keyboard shortcuts",
    "planner": "the Roadmap's Planner: goals and saved routes",
    "where_to_start": "the Roadmap's placement questions",
    "see_in_song": "in a Roadmap lesson on a song goal: the song itself, this lesson's bars marked",
}

TOOLS = [
    {
        "name": "start_practice",
        "description": "Start a practice run on the lesson currently on screen. Replaces any run "
                       "in progress. Bars and tempo apply to this run only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["listen", "learn", "rehearse"],
                         "description": "listen: the keyboard plays it and the cursor follows, nothing to play. "
                                        "learn: the cursor waits for the right notes. rehearse: moves at tempo."},
                "hand": {"type": "string", "enum": ["both", "right", "left"]},
                "bars": {"type": "string", "description": "Bar range like '5-8', or empty for the whole lesson."},
                "tempo_percent": {"type": "integer", "description": "Listen / Rehearse speed, 30-150. Default 100."},
                "loop": {"type": "boolean", "description": "Restart automatically after each completed pass."},
                "part": {"type": "string", "description": "Play one part of a band song with every other part as the "
                                                          "backing, by the instrument it's for: 'flute', 'strings'. "
                                                          "Found and saved the first time. Empty: the hand above."},
                "track": {"type": "string", "description": "With part: the track it is, when the last call asked which."},
                "lead_in_bars": {"type": "integer", "description": "With part: bars of backing before the part comes in, "
                                                                   "0-8 (saved for the song)."},
                "lead_in_every_pass": {"type": "boolean", "description": "With part and loop: replay the lead-in each "
                                                                         "pass (saved for the song)."},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_backing_volume",
        "description": "Turn one track the user isn't playing up, down or off ('drums down', 'mute the choir', "
                       "'turn the left hand off'). In Listen, any track. Saved for the song.",
        "input_schema": {
            "type": "object",
            "properties": {
                "part": {"type": "string", "description": "The backing part, by its name or instrument: 'drums'."},
                "volume_percent": {"type": "integer", "description": "0 (off) to 100 (as written)."},
            },
            "required": ["part", "volume_percent"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stop_practice",
        "description": "Stop the current practice run.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "play_passage",
        "description": "Play the lesson on screen through the keyboard so the pianist can hear "
                       "how it should sound.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bars": {"type": "string", "description": "Bar range like '1-4', or empty for all."},
                "hand": {"type": "string", "enum": ["both", "right", "left"]},
                "tempo_percent": {"type": "integer", "description": "Playback speed, 30-150. Default 100."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "progress",
        "description": "The pianist's score history on the lesson on screen: recent scores, and "
                       "bars that improved or keep going wrong.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "switch_lesson",
        "description": "Show a different saved lesson or piece, found by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Title or part of it, e.g. 'C major scale'."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_lesson",
        "description": "Compose a new practice exercise (scale, arpeggio, drill on a problem "
                       "bar...) and put it on screen. A specialist composer writes it, which "
                       "takes several seconds; tell the pianist it's coming.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "What to write, with key, hands, length and "
                                                             "difficulty if the pianist said them."},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hand_off",
        "description": "Pass a question that needs real teaching to the senior teacher (Claude on the "
                       "pianist's own subscription, with the keyboard, score and your voice), who "
                       "answers aloud as you within about a minute. If it can't, the question is "
                       "saved for Claude Desktop; the result says which.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The pianist's question in full, with what it "
                                                              "refers to (lesson, bars, hand) spelled out from the context."},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remember",
        "description": "Add one lasting fact about the pianist to your notebook (goals, pieces, weak "
                       "spots, preferences). Not for things that only matter today.",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "One short line."}},
            "required": ["note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_goal",
        "description": "Plan a new goal on the Roadmap (a song, a skill or a grade) and make it the active one. "
                       "Planning runs in the background on the pianist's subscription and takes a minute or "
                       "two (a song longer: its facts are looked up first); you announce the Path when it's ready.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The goal in the pianist's words, with anything they added."},
                "song": {"type": "string", "description": "For a song goal: the song file's name from their library, if they named one."},
                "artist": {"type": "string"},
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
    },
    {
        "name": "next_stop",
        "description": "Open the next step on the active goal's Path on the page, and say what it is.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "start_exam",
        "description": "Start (or resume) a mock exam for a grade on the page: pieces, scales, sight-reading, aural, out of 150.",
        "input_schema": {
            "type": "object",
            "properties": {"grade": {"type": "string", "enum": ["initial", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]}},
            "required": ["grade"],
            "additionalProperties": False,
        },
    },
    {
        "name": "atlas_summary",
        "description": "Where the pianist stands on the Roadmap: each grade's progress, mock exam results, the active goal.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "report_bug",
        "description": "Save a bug report about the app for the developer to fix later, with screenshots "
                       "of the screen now and in the seconds before, and the practice context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What's wrong, in the pianist's words, with what it "
                                                                 "refers to (page, lesson, bars, mode) spelled out from the context."},
                "add_to_last": {"type": "boolean", "description": "Add a screenshot and this description to the "
                                                                 "report just made instead of starting a new one."},
                "important": {"type": "boolean", "description": "They said it's important, urgent or a priority: "
                                                               "it's worked on before the rest."},
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_tiles",
        "description": "Change the quick-action tiles on the Maestro panel for one part of the app: add "
                       "tiles (to the end), take tiles off, or put that part back to its defaults. A tile "
                       "from another part works there too (it goes there first). Tiles: "
                       + "; ".join(f"{k}: {v}" for k, v in tiles.TILES.items()),
        "input_schema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": list(tiles.VIEWS),
                         "description": "; ".join(f"{k}: {v}" for k, v in tiles.VIEW_NAMES.items())
                                        + ". The part they're on unless they say."},
                "add": {"type": "array", "items": {"type": "string", "enum": list(tiles.TILES)}},
                "remove": {"type": "array", "items": {"type": "string", "enum": list(tiles.TILES)}},
                "reset": {"type": "boolean", "description": "Back to that part's default tiles first."},
            },
            "required": ["view"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_feature",
        "description": "Save a request for a change or new feature in the app itself (not a lesson or exercise, "
                       "which you make yourself) for the developer to build later, with screenshots and the practice context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What they want, in their words, with what it refers "
                                                                 "to (page, panel, button, mode) spelled out from the context."},
                "add_to_last": {"type": "boolean", "description": "Add a screenshot and this description to the "
                                                                 "request just made instead of starting a new one."},
                "important": {"type": "boolean", "description": "They said it's important, urgent or a priority: "
                                                               "it's worked on before the rest."},
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "page_control",
        "description": "Change what the coach page shows or how it's set up, without starting a run: "
                       "go to another part of the app, sheet or falling notes, labels, zoom, layout, the "
                       "metronome, tempo, bar range and loop. Set only what they asked for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["home", "session", "explore", "record", "roadmap", "youtube", "visualizer"],
                         "description": "Where to go. Leaving a session stops a run that's going. visualizer: the "
                                        "full-screen piano visualizer (light show, LEDs, video backgrounds)."},
                "show": {"type": "string", "enum": ["sheet", "notes", "both"],
                         "description": "Sheet music, the falling notes, or both."},
                "labels": {"type": "string", "enum": ["easy", "coached", "hard"],
                           "description": "easy: names and counting everywhere; coached: only where they slip; hard: none."},
                "note_names": {"type": "boolean"},
                "counting": {"type": "boolean"},
                "dynamics": {"type": "boolean"},
                "tab": {"type": "boolean", "description": "A guitar's or a bass's tab staff under the notes."},
                "fingering": {"type": "string", "enum": ["off", "repeats", "line"],
                              "description": "A flute's or a sax's fingering diagram under the notes: off; repeats: where the "
                                             "fingering changes; line: each note the first time on a line."},
                "fingering_monitor": {"type": "boolean",
                                      "description": "A flute's or a sax's monitor while playing: the expected note's fingering "
                                                     "beside the note the microphone hears."},
                "zoom_percent": {"type": "integer", "description": "How big the sheet is drawn, 50-200."},
                "layout": {"type": "string", "enum": ["line", "rows"],
                           "description": "line: scrolls sideways; rows: two rows, scrolls down."},
                "metronome": {"type": "boolean", "description": "Start (true) or stop (false) the metronome."},
                "metronome_bpm": {"type": "integer", "description": "20-300."},
                "tempo_percent": {"type": "integer", "description": "The next run's speed, 30-150."},
                "bars": {"type": "string", "description": "Bar range like '5-8' for the next run, or empty for the whole lesson."},
                "loop": {"type": "boolean", "description": "Repeat the bar range."},
                "menu": {"type": "string", "enum": list(PAGE_MENUS),
                         "description": "Open a menu or settings page and light it up, when they ask where "
                                        "something is or want to look themselves. "
                                        + "; ".join(f"{k}: {v}" for k, v in PAGE_MENUS.items())},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "open_song",
        "description": "Find a song or piece by name and put it on screen in the Session: the library first, "
                       "then their Downloads folder (a file from MuseScore or a website lands there), then "
                       "bitmidi.com. If it isn't anywhere, a MuseScore link to it goes in your panel for them to "
                       "download it; say so.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The song's title as they said it, e.g. 'Home for a Rest'."},
                "artist": {"type": "string", "description": "Who it's by, if they said: 'Spirit of the West'."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_from_today",
        "description": "Take something out of today's session plan (the Home page's Today list) when they "
                       "don't want it today. It stays out until tomorrow's plan or Plan again.",
        "input_schema": {
            "type": "object",
            "properties": {
                "what": {"type": "string", "description": "A title from the plan ('Thriller'), a part's label "
                                                          "('for fun', 'warm-up'), or 'all' for the whole plan."},
            },
            "required": ["what"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_style",
        "description": "Change how you coach from now on, including the remarks after each pass. "
                       "friend: a cheerful, encouraging practice buddy. strict: dry and demanding.",
        "input_schema": {
            "type": "object",
            "properties": {"style": {"type": "string", "enum": ["friend", "strict"]}},
            "required": ["style"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_talk",
        "description": "Change when you speak during a practice run. Set only what they asked about. "
                       "greet: say hello when they press Start. passes: after each finished pass, "
                       "every (always a remark), news (only when something changed; the default) "
                       "or off. sign_off: sum up when a run of passes ends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "greet": {"type": "boolean"},
                "passes": {"type": "string", "enum": ["every", "news", "off"]},
                "sign_off": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
]

LESSON_SYSTEM = """\
You compose short piano practice exercises for a practice app. Call create_lesson exactly once \
with the finished exercise. Write each hand in music21 tinyNotation, in its own clef \
(right = treble, left = bass):
- Pitches: c d e f g a b = C4 to B4; c' = C5, c'' = C6; C = C3, CC = C2.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), c'# (C#5) - never c#'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note \
without a number repeats the previous duration. Rests r4. Ties c2~ c8. Chords chord{C2 E G} \
(duration on the first note). Triplets trip{c8 d e}.
- Fill every bar of the time signature exactly in both hands; use rests for a silent hand \
(e.g. hands separate: right hand plays bars 1-4 while the left has r1 r1 r1 r1, then swap).
If the tool reports an error, fix the notation and call it again.\
"""

FLUTE_LESSON_SYSTEM = """\
You compose short flute practice exercises for a beginner (first notes to Grade 2) in a \
practice app. Call create_lesson exactly once with the finished exercise. The flute plays one \
line: write it in "right" in music21 tinyNotation (treble clef) and leave "left" empty.
- Pitches: c d e f g a b = C4 to B4; c' = C5, c'' = C6. Keep to E4-G5 (e to g') unless asked \
for higher; the flute's whole range is C4-C7.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), f'# (F#5), e'- (Eb5) - never e-'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note \
without a number repeats the previous duration. Rests r4. Ties c2~ c8. No chords.
- Fill every bar of the time signature exactly. Leave room to breathe: a rest or a long note \
every two to four bars. Beginners: crotchets, minims and quaver pairs, slow tempos (60-80).
If the tool reports an error, fix the notation and call it again.\
"""

SAX_LESSON_SYSTEM = """\
You compose short alto saxophone practice exercises for a beginner (first notes to Grade 2) \
in a practice app. Call create_lesson exactly once with the finished exercise. The saxophone \
plays one line: write it in "right" in music21 tinyNotation (treble clef, written pitch) and \
leave "left" empty.
- Pitches: c d e f g a b = C4 to B4; c' = C5, c'' = C6. Keep to D4-C6 (d to c'') unless asked \
for lower; the alto's written range is B flat 3 to F6.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), f'# (F#5), e'- (Eb5) - never e-'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note \
without a number repeats the previous duration. Rests r4. Ties c2~ c8. No chords.
- Fill every bar of the time signature exactly. Leave room to breathe: a rest or a long note \
every two to four bars. Beginners: crotchets, minims and quaver pairs, slow tempos (60-80).
If the tool reports an error, fix the notation and call it again.\
"""

VOICE_LESSON_SYSTEM = """\
You compose short singing exercises for a beginner (first notes to Grade 2) in a practice \
app. Call create_lesson exactly once with the finished exercise. A voice sings one line: write \
it in "right" in music21 tinyNotation (treble clef, written for a high voice; a low voice \
sings it an octave down) and leave "left" empty.
- Pitches: c d e f g a b = C4 to B4; c' = C5. Keep to C4-D5 (c to d') unless asked for wider; \
the course's whole range is A3-G5.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), c'# (C#5), e'- (Eb5) - never e-'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth; dots c4.; a note without \
a number repeats the previous duration. Rests r4. Ties c2~ c8. No chords.
- Fill every bar of the time signature exactly. Mostly steps, few leaps (a third, then a \
fifth), a breath (a rest or a long note) every two bars. Slow tempos (60-80).
If the tool reports an error, fix the notation and call it again.\
"""
STRING_LESSON_SYSTEM = """\
You compose short {name} practice exercises for a beginner (first notes to Grade 2) in a \
practice app. Call create_lesson exactly once with the finished exercise. The coach grades one \
line: write it in "right" in music21 tinyNotation ({clef}) and leave "left" empty.
- Pitches: {pitches} Keep to {keep} unless asked for wider.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), c'# (C#5), F# (F#3) - never c#'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note \
without a number repeats the previous duration. Rests r4. Ties c2~ c8. No chords.
- Fill every bar of the time signature exactly. Beginners: crotchets, minims and quaver pairs, \
slow tempos (60-80), {style}.
If the tool reports an error, fix the notation and call it again.\
"""
FIDDLE_LESSON_SYSTEM = STRING_LESSON_SYSTEM.format(
    name="fiddle", clef="treble clef, as it sounds",
    pitches="c d e f g a b = C4 to B4; c' = C5, c'' = C6; G A B = G3 to B3.",
    keep="first position, G3-B5 (G to b'); the open strings are G3, D4, A4 and E5",
    style="mostly in D, G and A major, steps and string crossings")
GUITAR_LESSON_SYSTEM = STRING_LESSON_SYSTEM.format(
    name="electric guitar", clef="written pitch, an octave above how the guitar sounds, as guitar music is printed",
    pitches="c d e f g a b = C4 to B4; c' = C5; E F G A B = E3 to B3.",
    keep="first position, written E3-G5 (E to g'); the open strings are written E3, A3, D4, G4, B4 and E5",
    style="single notes only (melodies, riffs, scales; spell a chord out one note at a time)")
BASS_LESSON_SYSTEM = STRING_LESSON_SYSTEM.format(
    name="bass guitar", clef="written pitch, an octave above how the bass sounds, as bass music is printed in the bass clef",
    pitches="C D E F G A B = C3 to B3; CC = C2, EE = E2; c = C4.",
    keep="first position, written E2-C4 (EE to c); the open strings are written E2, A2, D3 and G3",
    style="roots and fifths, steps, rests that stop the notes cleanly")
LESSON_SYSTEMS = {"flute": FLUTE_LESSON_SYSTEM, "sax": SAX_LESSON_SYSTEM, "voice": VOICE_LESSON_SYSTEM,
                  "fiddle": FIDDLE_LESSON_SYSTEM, "guitar": GUITAR_LESSON_SYSTEM, "bass": BASS_LESSON_SYSTEM}

# Added to every instrument's prompt: the page can be worked by voice.
PAGE_SYSTEM = """

When they ask to change the screen (show the falling notes, note names on, zoom in, the \
metronome, open the Roadmap or Home), do it with page_control rather than telling them where \
to click. To set the bars, tempo or loop and start playing at once, use start_practice instead. \
When they ask where a setting is, or want to change one page_control can't set, open its menu \
with page_control's menu (it lights up on their screen) and say in a few words what to pick \
there. If no menu fits, say you can't open that yet.

When they name a song or piece to play or open ("home for a rest", "put on Desperado", a title and its artist), call open_song with the title, even when a word of it sounds like a command ("home", "rest", "stop"); a title they say beside a page name is still a song. switch_lesson is for exercises and lessons already saved. When they don't want something in today's plan ("skip Thriller", "drop the warm-up", "clear today's plan"), use remove_from_today.

"Stop" alone means the run. To cut you short (you finish your sentence and say no more) they \
press ■ Stop or Esc while you talk, or say "that's enough": the app does it without you. Tell \
them so when they ask how."""

# Added to either Maestro's prompt for a young learner's profile.
YOUNG_SYSTEM = """

This pupil is a young child, about four to eight, just starting out, and may not read yet. Talk to them directly, warmly and simply: very short sentences, everyday words, one idea at a time, and praise every real try before one small thing to fix. Name keys by letter and finger number ("your thumb on C"), and use only the words their first lessons teach: high and low, loud and quiet, steps and skips, ta and ta-a, the beat. No percentages or jargon: say "nearly all the right keys" or "that was nice and steady". Suggest a wiggle break or a game when they struggle twice in a row. If a grown-up is clearly the one speaking, answer them normally. Their path starts at the Roadmap's First steps, then Ready to read, before Initial."""
YOUNG_LESSON_SYSTEM = """

The pupil is a young child just starting out: keep to one five-finger position (right hand c to g, or left hand C to G, unless asked otherwise), crotchets, minims and semibreves only (no quavers, dots or rests unless asked), at most eight bars, one hand at a time or hands taking turns, tempo 60-80, and give it a friendly title."""

CREATE_LESSON_TOOL = {
    "name": "create_lesson",
    "description": "Validate, save and show the exercise. Returns a bar-by-bar readout or an error.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "right": {"type": "string", "description": "Right hand tinyNotation, or empty."},
            "left": {"type": "string", "description": "Left hand tinyNotation, or empty."},
            "time_signature": {"type": "string", "description": "e.g. '4/4'"},
            "key": {"type": "string", "description": "'C', 'G', 'Bb', 'F#m' (minor with m)..."},
            "tempo_bpm": {"type": "integer"},
        },
        "required": ["title", "right", "left", "time_signature", "key", "tempo_bpm"],
        "additionalProperties": False,
    },
}


class Unavailable(RuntimeError):
    pass


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    path = home() / "anthropic_api_key.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def daily_cap() -> float:
    try:
        return float(os.environ.get("MIDI_COACH_DAILY_CAP") or DEFAULT_DAILY_CAP)
    except ValueError:
        return DEFAULT_DAILY_CAP


def request_cost(model: str, usage) -> float:
    price_in, price_out = PRICES.get(model, PRICES[LESSON_MODEL])
    fresh = getattr(usage, "input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (fresh * price_in + written * price_in * 1.25 + read * price_in * 0.1 + out * price_out) / 1_000_000


class Ledger:
    """Dollars spent per day, kept on disk so the cap survives restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _path(self):
        return home() / "ai_spend.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def today(self) -> float:
        with self._lock:
            return float(self._load().get(time.strftime("%Y-%m-%d"), 0.0))

    def add(self, dollars: float) -> float:
        with self._lock:
            data = self._load()
            day = time.strftime("%Y-%m-%d")
            data[day] = round(float(data.get(day, 0.0)) + dollars, 6)
            data["total"] = round(float(data.get("total", 0.0)) + dollars, 6)
            self._path().write_text(json.dumps(data, indent=1), encoding="utf-8")
            return data[day]


class VoiceChat:
    """One ongoing conversation with the Maestro.

    actions: name -> callable(**tool_input) -> dict, for every tool in TOOLS except
    write_lesson, plus 'create_lesson' (used by the lesson writer).
    context: callable() -> str describing the practice right now.
    instrument: callable() -> 'piano', 'flute', 'sax' or 'voice', the active profile's (who the Maestro teaches).
    """

    def __init__(self, actions: dict, context, client=None, instrument=None, young=None) -> None:
        self.actions = actions
        self.context = context
        self.instrument = instrument or (lambda: "piano")
        self.young = young or (lambda: False)  # a young learner's profile: simpler words
        self._client = client
        self.ledger = Ledger()
        self.messages: list = []
        self._last_turn = 0.0
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if self._client is not None:
            return True, ""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "The anthropic package isn't installed (pip install anthropic)."
        if not api_key():
            return False, f"No API key. Put it in {home() / 'anthropic_api_key.txt'} or set ANTHROPIC_API_KEY."
        return True, ""

    def status(self) -> dict:
        ok, why = self.available()
        return {"available": ok, "reason": why, "spent_today": round(self.ledger.today(), 4), "cap": daily_cap()}

    def client(self):
        if self._client is None:
            ok, why = self.available()
            if not ok:
                raise Unavailable(why)
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key())
        return self._client

    def _meter(self, model: str, response) -> float:
        cost = request_cost(model, response.usage)
        self.ledger.add(cost)
        return cost

    def ask(self, said: str) -> dict:
        """Answer what the pianist said. Returns {reply, cost, actions, spent_today}."""
        said = " ".join((said or "").split())
        if not said:
            return {"error": "I didn't catch anything."}
        if not self._lock.acquire(blocking=False):
            return {"error": "Still answering the last thing you said."}
        try:
            return self._ask(said)
        finally:
            self._lock.release()

    def start_fresh_if_due(self) -> bool:
        """Start a fresh conversation after a break or a long chat; True if one was forgotten
        (the Maestro panel draws a line there). Earlier turns are never edited: that would
        invalidate the replayed thinking blocks."""
        if self.messages and (time.time() - self._last_turn > NEW_CONVERSATION_AFTER_SEC
                              or len(self.messages) > NEW_CONVERSATION_AFTER_MESSAGES):
            self.messages = []
            return True
        return False

    def _ask(self, said: str) -> dict:
        if self.ledger.today() >= daily_cap():
            return {"reply": "That's enough talking for today. We've hit the daily budget. Play, don't chat.",
                    "cost": 0.0, "actions": [], "spent_today": self.ledger.today(), "capped": True}
        self.start_fresh_if_due()
        self._last_turn = time.time()
        player = PLAYERS.get(self.instrument(), "pianist")
        self.messages.append({"role": "user", "content": f"[Practice context]\n{self.context()}\n\n[The {player} said]\n{said}"})
        cost, done = 0.0, []
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client().messages.create(
                model=CHAT_MODEL,
                max_tokens=2000,
                system=SYSTEMS.get(self.instrument(), SYSTEM) + PART_SYSTEM + PAGE_SYSTEM + (YOUNG_SYSTEM if self.young() else ""),
                tools=TOOLS,
                messages=self.messages,
                output_config={"effort": "low"},
                cache_control={"type": "ephemeral"},
            )
            cost += self._meter(CHAT_MODEL, response)
            if response.stop_reason == "refusal":
                self.messages = []  # start over rather than edit the history
                reply = f"Let's keep this about {TOPICS.get(self.instrument(), 'the piano')}."
                break
            self.messages.append({"role": "assistant", "content": response.content})
            reply = " ".join(b.text for b in response.content if b.type == "text").strip() or reply
            uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not uses:
                break
            results = []
            for use in uses:
                out, extra = self._run_tool(use.name, dict(use.input or {}))
                cost += extra
                done.append(use.name)
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(out, default=str)[:4000],
                                **({"is_error": True} if isinstance(out, dict) and "error" in out else {})})
            self.messages.append({"role": "user", "content": results})
        return {"reply": reply or "Hm.", "cost": round(cost, 5), "actions": done, "spent_today": round(self.ledger.today(), 4)}

    def _run_tool(self, name: str, args: dict) -> tuple[dict, float]:
        try:
            if name == "write_lesson":
                return self._write_lesson(args.get("request", ""))
            action = self.actions.get(name)
            if action is None:
                return {"error": f"unknown tool {name}"}, 0.0
            return action(**args), 0.0
        except Exception as exc:  # the model gets the error and can explain it
            log.warning("voice tool %s failed: %s", name, exc)
            return {"error": str(exc)}, 0.0

    def _write_lesson(self, request: str) -> tuple[dict, float]:
        if self.ledger.today() >= daily_cap():
            return {"error": "Daily AI budget reached; no lesson writing today."}, 0.0
        messages = [{"role": "user", "content": f"{request}\n\nCurrent practice, for reference:\n{self.context()}"}]
        cost = 0.0
        for _ in range(3):
            response = self.client().beta.messages.create(
                model=LESSON_MODEL,
                max_tokens=8000,
                system=LESSON_SYSTEMS.get(self.instrument(), LESSON_SYSTEM) + (YOUNG_LESSON_SYSTEM if self.young() else ""),
                tools=[CREATE_LESSON_TOOL],
                messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            cost += self._meter(LESSON_MODEL, response)
            if response.stop_reason == "refusal":
                return {"error": "The composer declined that request."}, cost
            uses = [b for b in response.content if b.type == "tool_use" and b.name == "create_lesson"]
            if not uses:
                return {"error": "The composer didn't write a lesson."}, cost
            messages.append({"role": "assistant", "content": response.content})
            results, created = [], None
            for use in uses:
                try:
                    out = self.actions["create_lesson"](**dict(use.input))
                except Exception as exc:
                    out = {"error": str(exc)}
                if "error" not in out and created is None:
                    created = out
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(out, default=str)[:6000],
                                **({"is_error": True} if "error" in out else {})})
            if created:
                return {"created": created.get("path"), "bars": created.get("bars"), "on_screen": True}, cost
            messages.append({"role": "user", "content": results})
        return {"error": "The composer couldn't get the notation right."}, cost
