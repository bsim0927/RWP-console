//! Rust build of `sg.dataroom.match_quote_py`. It must return exactly what the Python does,
//! including its quirks; tests/test_match_quote.py runs both and compares them.

/// The next quoted word is at most this many words on (5 between), e.g. a left-column label.
const MAX_GAP: usize = 6;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Match {
    Exact,
    Reflowed,
}

impl Match {
    pub fn as_str(self) -> &'static str {
        match self {
            Match::Exact => "exact",
            Match::Reflowed => "reflowed",
        }
    }
}

/// Python's `str.isspace`, which is what `\s` matches. It is Unicode White_Space plus the
/// four information separators U+001C..U+001F, which Rust's `is_whitespace` leaves out.
fn py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `re.sub(r"\s+", " ", s).strip().lower()`
fn norm(s: &str) -> String {
    s.split(py_space).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ").to_lowercase()
}

/// `re.findall(r"[a-z0-9$%.]+", s.lower())`. Python also maps ’ to ', but neither is a word
/// character, so that step changes nothing here.
fn words(s: &str) -> Vec<String> {
    let lower = s.to_lowercase();
    lower
        .split(|c: char| !matches!(c, 'a'..='z' | '0'..='9' | '$' | '%' | '.'))
        .filter(|w| !w.is_empty())
        .map(str::to_owned)
        .collect()
}

pub fn match_quote(text: &str, quote: &str) -> Option<Match> {
    let normed = norm(quote);
    if normed.is_empty() {
        return None;
    }
    if norm(text).contains(&normed) {
        return Some(Match::Exact);
    }
    let (q, t) = (words(quote), words(text));
    if q.len() < 5 {
        return None;
    }
    let max_span = q.len() as f64 * 1.3 + 4.0;
    for start in (0..t.len()).filter(|&i| t[i] == q[0]) {
        // Every position the current quote word can sit at. Keeping all of them, not just the
        // nearest, matters when a word repeats: a later "the" may be the one that reaches on.
        let mut reach = vec![start];
        for want in &q[1..] {
            let mut next: Vec<usize> = reach
                .iter()
                .flat_map(|&p| p + 1..(p + 1 + MAX_GAP).min(t.len()))
                .filter(|&k| t[k] == *want)
                .collect();
            next.sort_unstable();
            next.dedup();
            reach = next;
            if reach.is_empty() {
                break;
            }
        }
        if let Some(&end) = reach.first() {
            if (end - start + 1) as f64 <= max_span {
                return Some(Match::Reflowed);
            }
        }
    }
    None
}

#[cfg(feature = "python")]
#[pyo3::pymodule]
mod _verify {
    use pyo3::prelude::*;

    /// match_quote(text, quote) -> 'exact' | 'reflowed' | None
    #[pyfunction]
    #[pyo3(signature = (text, quote))]
    fn match_quote(py: Python<'_>, text: &str, quote: Option<&str>) -> Option<&'static str> {
        let quote = quote?;
        py.detach(|| super::match_quote(text, quote)).map(super::Match::as_str)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_and_reflowed() {
        assert_eq!(match_quote("Minimum\n Investment: $1", "minimum investment: $1"), Some(Match::Exact));
        assert_eq!(
            match_quote("the minimum Amount: initial investment is high", "the minimum initial investment is high"),
            Some(Match::Reflowed)
        );
        assert_eq!(match_quote("anything", ""), None);
        assert_eq!(match_quote("anything", " \n "), None);
    }

    #[test]
    fn python_whitespace_set() {
        assert_eq!(norm("a\u{1c}b\u{a0}c  "), "a b c");
        assert_eq!(norm("a\u{200b}b"), "a\u{200b}b"); // zero-width space is not whitespace
    }

    #[test]
    fn words_keep_money_and_percent() {
        assert_eq!(words("Fee: $2.5 (3%)"), ["fee", "$2.5", "3%"]);
    }
}
