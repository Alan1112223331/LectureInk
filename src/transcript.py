"""Live bilingual transcript: segments (utterances) grouped into paragraphs.

Each segment carries final text plus a provisional ("live") tail for both the source and the
translation. Engines only send segment updates; paragraphing and rendering live here.
"""
from __future__ import annotations
import dataclasses
import html
import json
import re
import time
from pathlib import Path

SPACELESS = ('zh', 'ja', 'th', 'lo', 'my')
LINE_BREAK = '\u2028'
PUNCTUATION = set('。！？，、；：…—.!?,;:"”’）)》」』')
CJK = r'\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef'
CJK_PUNCT = r'\u3000-\u303f\uff01-\uff0f\uff1a-\uff20\u2014\u2026\u201c\u201d'
# Spaces next to Chinese punctuation, or between two Chinese characters, are tokenizer artefacts.
# A space between Chinese and a Latin word ("两个 C 之间") is normal typesetting and is kept.
_CJK_SPACES = re.compile(rf'(?<=[{CJK_PUNCT}])[ \t]+|[ \t]+(?=[{CJK_PUNCT}])|(?<=[{CJK}])[ \t]+(?=[{CJK}])')


def tidy_spaceless(text: str) -> str:
    return _CJK_SPACES.sub('', text)


@dataclasses.dataclass
class Segment:
    id: str
    src: str = ''
    src_live: str = ''
    tgt: str = ''
    tgt_live: str = ''
    start: float | None = None
    end: float | None = None
    closed: bool = False
    paragraph: int = 0


def _spaced(language: str) -> bool:
    return not language.lower().startswith(SPACELESS)


class Transcript:
    PARA_GAP = 2.5      # seconds of silence before a new paragraph
    PARA_CHARS = 520    # long monologues still break at the next utterance

    def __init__(self, source_language: str = 'en', target_language: str = 'zh'):
        self.source_language = source_language
        self.target_language = target_language
        self.segments: list[Segment] = []
        self.paragraphs: list[list[int]] = []
        self._index: dict[str, int] = {}
        self._dirty: int | None = None
        self.revision = 0

    # ---- updates -------------------------------------------------------------------------------
    def apply(self, update: dict) -> None:
        sid = str(update['id'])
        if sid in self._index:
            seg = self.segments[self._index[sid]]
        else:
            seg = Segment(sid, start=update.get('start'))
            seg.paragraph = self._paragraph_for(seg)
            self._index[sid] = len(self.segments)
            self.segments.append(seg)
            if seg.paragraph == len(self.paragraphs):
                self.paragraphs.append([])
            self.paragraphs[seg.paragraph].append(self._index[sid])
        for key in ('src', 'src_live', 'tgt', 'tgt_live', 'start', 'end', 'closed'):
            if key in update and update[key] is not None:
                setattr(seg, key, update[key])
        self._mark(seg.paragraph)

    def _paragraph_for(self, seg: Segment) -> int:
        if not self.segments:
            return 0
        prev = self.segments[-1]
        current = prev.paragraph
        if seg.start is not None and prev.end is not None and seg.start - prev.end >= self.PARA_GAP:
            return current + 1
        if len(self.text(current, 'src')) >= self.PARA_CHARS:
            return current + 1
        return current

    def _mark(self, paragraph: int) -> None:
        self._dirty = paragraph if self._dirty is None else min(self._dirty, paragraph)
        self.revision += 1

    def take_dirty(self) -> int | None:
        dirty, self._dirty = self._dirty, None
        return dirty

    def clear(self) -> None:
        self.segments.clear()
        self.paragraphs.clear()
        self._index.clear()
        self._dirty = 0
        self.revision += 1

    # ---- reading -------------------------------------------------------------------------------
    def separator(self, side: str) -> str:
        return ' ' if _spaced(self.source_language if side == 'src' else self.target_language) else ''

    def runs(self, paragraph: int, side: str) -> list[tuple[str, bool]]:
        """Styled runs `(text, is_live)` of one paragraph, segments joined by the language's separator."""
        out: list[tuple[str, bool]] = []
        sep = self.separator(side)
        previous = ''
        for i in self.paragraphs[paragraph]:
            seg = self.segments[i]
            final, live = (seg.src, seg.src_live) if side == 'src' else (seg.tgt, seg.tgt_live)
            if not sep:
                final, live = _tidy_pair(final, live)
            final, live = _trim(final, live)
            if not final and not live:
                continue
            if previous and sep:
                out.append((sep, False))
            elif previous and previous[-1] not in PUNCTUATION:
                # Utterances cut at a pause without punctuation still need a visible break in CJK text.
                out.append(('，', False))
            out.append((final, False))
            out.append((live, True))
            previous = final + live
        return _merge(out)

    def text(self, paragraph: int, side: str, include_live: bool = True) -> str:
        return ''.join(t for t, live in self.runs(paragraph, side) if include_live or not live)

    def recent_runs(self, side: str, paragraphs: int = 2) -> list[tuple[str, bool]]:
        """Whole recent paragraphs for captions, separated by line breaks. Whole paragraphs keep their
        line wrapping stable, so caption lines never reflow as text is added."""
        picked: list[list[tuple[str, bool]]] = []
        for p in range(len(self.paragraphs) - 1, -1, -1):
            runs = self.runs(p, side)
            if runs:
                picked.insert(0, runs)
                if len(picked) == paragraphs:
                    break
        out: list[tuple[str, bool]] = []
        for runs in picked:
            if out:
                out.append((LINE_BREAK, False))
            out.extend(runs)
        return _merge(out)

    def is_empty(self) -> bool:
        return not any(s.src or s.src_live or s.tgt or s.tgt_live for s in self.segments)

    # ---- persistence and export ----------------------------------------------------------------
    def to_dict(self) -> dict:
        return {'version': 2, 'source_language': self.source_language, 'target_language': self.target_language,
                'segments': [dataclasses.asdict(s) for s in self.segments]}

    @classmethod
    def from_dict(cls, data: dict) -> 'Transcript':
        t = cls(data.get('source_language', 'en'), data.get('target_language', 'zh'))
        for raw in data.get('segments', []):
            seg = Segment(**{k: v for k, v in raw.items() if k in Segment.__dataclass_fields__})
            seg.src, seg.src_live = seg.src + seg.src_live, ''
            seg.tgt, seg.tgt_live = seg.tgt + seg.tgt_live, ''
            t._index[seg.id] = len(t.segments)
            t.segments.append(seg)
            while len(t.paragraphs) <= seg.paragraph:
                t.paragraphs.append([])
            t.paragraphs[seg.paragraph].append(t._index[seg.id])
        t.paragraphs = [p for p in t.paragraphs if p]
        for n, members in enumerate(t.paragraphs):
            for i in members:
                t.segments[i].paragraph = n
        t._dirty = 0
        return t

    def save(self, path: Path) -> None:
        from settings import atomic_json
        atomic_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> 'Transcript':
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))

    def pairs(self) -> list[tuple[str, str]]:
        return [(self.text(p, 'src'), self.text(p, 'tgt')) for p in range(len(self.paragraphs))]

    def export(self, fmt: str, title: str = '', topic: str = '', which: str = 'both') -> str:
        pairs = [(s, t) for s, t in self.pairs() if s.strip() or t.strip()]
        stamp = time.strftime('%Y-%m-%d %H:%M')
        if fmt == 'html':
            rows = ''.join('<tr>' + ('<td class="src">' + html.escape(s) + '</td>' if which != 'target' else '')
                           + ('<td>' + html.escape(t) + '</td>' if which != 'source' else '') + '</tr>' for s, t in pairs)
            return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>' + html.escape(title) + '</title>'
                    '<style>body{max-width:1180px;margin:48px auto;padding:0 24px;font:17px/1.75 "Microsoft YaHei UI",'
                    'system-ui;color:#22332b;background:#fbfbf7}td{vertical-align:top;padding:8px 16px 14px 0}'
                    '.src{color:#55665c;font-family:"Segoe UI",system-ui;width:50%}h1{font-size:26px}'
                    '.meta{color:#7a877f}</style><h1>' + html.escape(title) + '</h1><p class="meta">'
                    + html.escape(' · '.join(x for x in (topic, stamp) if x)) + '</p><table>' + rows + '</table></html>')
        lines = [('# ' if fmt == 'md' else '') + title]
        meta = ' · '.join(x for x in (topic, stamp) if x)
        if meta:
            lines.append(('*' + meta + '*') if fmt == 'md' else meta)
        lines.append('')
        for s, t in pairs:
            if which != 'target' and s:
                lines.append(('> ' + s) if fmt == 'md' and which == 'both' else s)
                if which == 'both':
                    lines.append('')
            if which != 'source' and t:
                lines.append(t)
            lines.append('')
        return '\n'.join(lines)


def _tidy_pair(final: str, live: str) -> tuple[str, str]:
    """Tidy CJK spacing inside each part and across the final/live boundary."""
    final, live = tidy_spaceless(final), tidy_spaceless(live)
    head, tail = final.rstrip(' \t'), live.lstrip(' \t')
    if head != final and tail and _boundary_space_is_noise(head[-1:], tail[0]):
        final = head
    if tail != live and final and tail and _boundary_space_is_noise(final[-1], tail[0]):
        live = tail
    return final, live


def _boundary_space_is_noise(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if re.match(f'[{CJK_PUNCT}]', left) or re.match(f'[{CJK_PUNCT}]', right):
        return True
    return bool(re.match(f'[{CJK}]', left) and re.match(f'[{CJK}]', right))


def _trim(final: str, live: str) -> tuple[str, str]:
    text = final + live
    lead = len(text) - len(text.lstrip())
    if lead:
        cut = min(lead, len(final))
        final, live = final[cut:], live[lead - cut:]
    trail = len(text) - len(text.rstrip())
    if trail:
        cut = min(trail, len(live))
        live = live[:len(live) - cut]
        final = final[:len(final) - (trail - cut)] if trail > cut else final
    return final, live


def _merge(runs: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    merged: list[tuple[str, bool]] = []
    for text, live in runs:
        if not text:
            continue
        if merged and merged[-1][1] == live:
            merged[-1] = (merged[-1][0] + text, live)
        else:
            merged.append((text, live))
    return merged
