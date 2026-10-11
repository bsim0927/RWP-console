// Unit tests for the pure helpers in web/js/lib.js: formatting, status vocabulary, escaping, markdown.
import { describe, expect, it } from 'vitest';
import {
  bytes, dispNote, dispShort, dispTone, esc, extOf, gateName, markdown, mergedPath, n, pct,
  rawUrl, resultTone, sortGates, splitName, stampDate, initials,
} from '../../web/js/lib.js';

describe('esc', () => {
  it('escapes every HTML-significant character', () => {
    expect(esc(`<a href="x" title='y'>&</a>`)).toBe('&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;');
  });
  it('renders null and undefined as empty', () => {
    expect(esc(null)).toBe('');
    expect(esc(undefined)).toBe('');
  });
});

describe('number formatting', () => {
  it('n uses a dash for missing values', () => {
    expect(n(null)).toBe('–');
    expect(n(NaN)).toBe('–');
    expect(n(1234567)).toBe('1,234,567');
    expect(n(1.5, 2)).toBe('1.50');
  });
  it('pct scales fractions', () => {
    expect(pct(0.256)).toBe('26%');
    expect(pct(0.256, 1)).toBe('25.6%');
    expect(pct(null)).toBe('–');
  });
  it('bytes picks a unit', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(2048)).toBe('2 KB');
    expect(bytes(5 * 1048576)).toBe('5.0 MB');
  });
});

describe('stampDate', () => {
  it('parses run stamps (YYYYMMDDTHHMMSS)', () => {
    const d = stampDate('20261010T154400');
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()]).toEqual([2026, 9, 10, 15, 44]);
  });
  it('returns null for an empty stamp', () => expect(stampDate('')).toBeNull());
});

describe('names', () => {
  it('gateName humanises ids', () => expect(gateName('total_annual_cost')).toBe('Total annual cost'));
  it('splitName splits manager from strategy on the first " - "', () => {
    expect(splitName('Monroe Capital - ABF - II')).toEqual({ manager: 'Monroe Capital', strategy: 'ABF - II' });
    expect(splitName('Solo')).toEqual({ manager: 'Solo', strategy: '' });
  });
  it('initials takes two leading letters', () => expect(initials('General Atlantic - GAGE')).toBe('GA'));
  it('sortGates follows the canonical gate order', () => {
    expect(sortGates(['track_record', 'investor_eligibility', 'operability'])).toEqual(['investor_eligibility', 'operability', 'track_record']);
  });
});

describe('status vocabulary', () => {
  it.each([
    ['Pass', 'good'], ['Fail', 'crit'], ['Incomplete', 'warn'], ['Route with disclosure', 'serious'],
    ['Not yet run', 'none'], [undefined, 'none'],
  ])('resultTone(%s) = %s', (r, tone) => expect(resultTone(r)).toBe(tone));

  it.each([
    ['Coverable, subject to conditions', 'good'],
    ['Reviewed and not covered (draft, name the failed gate)', 'crit'],
    ['Under review (analyst to confirm one or more gates)', 'warn'],
    [null, 'none'],
  ])('dispTone(%s) = %s', (d, tone) => expect(dispTone(d)).toBe(tone));

  it('dispShort and dispNote split the trailing note', () => {
    const d = 'Under review (gates that cannot be closed are named)';
    expect(dispShort(d)).toBe('Under review');
    expect(dispNote(d)).toBe('gates that cannot be closed are named');
    expect(dispShort(null)).toBe('Not screened');
    expect(dispNote('Coverable')).toBe('');
  });
});

describe('paths', () => {
  it('mergedPath strips the Drive download part prefix', () => {
    expect(mergedPath('RWP-20261006T224806Z-1-001/RWP/1-Intake/a.pdf')).toBe('1-Intake/a.pdf');
    expect(mergedPath('1-Intake/a.pdf')).toBe('1-Intake/a.pdf');
  });
  it('rawUrl encodes the path and adds a page anchor', () => {
    expect(rawUrl('a b/c&d.pdf', 3)).toBe('/api/raw?path=a+b%2Fc%26d.pdf#page=3');
    expect(rawUrl('x.pdf')).toBe('/api/raw?path=x.pdf');
  });
  it('extOf lower-cases the extension', () => expect(extOf('Deck.PDF')).toBe('pdf'));
});

describe('markdown', () => {
  it('renders numbered lists, as the screen note request list uses', () => {
    const html = markdown('Asks:\n\n1. The fee schedule\n2. The valuation policy\n\nDone.');
    expect(html).toContain('<ol><li>The fee schedule</li><li>The valuation policy</li></ol>');
    expect(html).toContain('<p>Done.</p>');
  });

  it('renders headings, emphasis, code and lists', () => {
    const html = markdown('# Title\n\nSome **bold** and *em* and `code`.\n\n- one\n- two');
    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>em</em>');
    expect(html).toContain('<code>code</code>');
    expect(html).toContain('<ul><li>one</li><li>two</li></ul>');
  });
  it('renders tables and skips the separator row', () => {
    const html = markdown('| Gate | Result |\n|---|---|\n| operability | Pass |');
    expect(html).toContain('<th>Gate</th>');
    expect(html).toContain('<td>Pass</td>');
    expect(html).not.toContain('---');
  });
  it('escapes HTML in source text (run reports quote untrusted documents)', () => {
    const html = markdown('<img src=x onerror=alert(1)>\n\n| <script>x</script> |\n|---|\n| ok |');
    expect(html).not.toMatch(/<img|<script/);
    expect(html).toContain('&lt;img');
  });
});
