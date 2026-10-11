-- Gate rules from the CIO's screen decisions of 2026-10-11 (decision ids A1 to D4 are cited inline).
-- Each live gate is copied to gate_history first, exactly as a console edit would, and the new
-- definition becomes the next version after whatever is live, so console edits made since the seed are
-- kept in history and run records stay unambiguous. Disclosure history is not touched.

insert into public.gate_history (gate_id, position, yaml, version, reason)
select id, position, yaml, version, 'edit'
from public.gates
where id in ('investor_eligibility', 'total_annual_cost', 'operability', 'track_record')
order by position;

update public.gates g
set version = g.version + 1,
    yaml = regexp_replace(v.yaml, '^version: \d+', 'version: ' || (g.version + 1), 'n'),
    updated_at = now()
from (values
('investor_eligibility', $yaml$id: investor_eligibility
version: 3
extractor:
  sources:   # document types in priority order, then section-title patterns
    doc_types: [terms, offering document, subscription, ddq, governing agreement, deck]
    sections: ["minimum (initial )?(purchase|investment|commitment|subscription)", "suitability", "prospective investors", "eligib", "investor (qualification|standard|requirements)", "accredited", "qualified (purchaser|client)", "^the offering$", "unregistered securities"]
  keywords: [accredited investor, qualified purchaser, qualified client, institutional investor, minimum investment, 3(c)(7), 3(c)(1), suitability, eligible investor]
  rules: "Quote the sentence that states who may invest, the minimum, and the exemption the fund relies on."
  fields:
    - { name: investor_standard, description: "Who may invest: accredited investor, qualified client, qualified purchaser, institutional" }
    - { name: minimum_investment, description: "Minimum initial investment (recorded; never decides the gate)" }
    - { name: exemption, description: "Fund exemption, e.g. 3(c)(1) or 3(c)(7) (recorded; never decides the gate)" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` state who may invest in the fund?" }
  - { id: institutions_only, type: bool, q: "Does `facts.investor_standard` limit the fund to institutional investors, so that no individual investor may invest, not even a qualified purchaser?" }
  - { id: qp_only, type: bool, q: "Does `facts.investor_standard` limit the fund to qualified purchasers, excluding accredited investors who are not qualified purchasers?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { if: "institutions_only >= 0.7", then: Fail }   # no RWP client can hold it (A4)
  - { then: Pass }   # a QP-only fund passes with a flag (A2); the minimum never fails (A3)
flags:
  - { if: "sufficient >= 0.7 and qp_only >= 0.7 and institutions_only < 0.7", flag: QP-only }
$yaml$),
('total_annual_cost', $yaml$id: total_annual_cost
version: 3
extractor:
  sources:
    doc_types: [terms, offering document, governing agreement, ddq, deck]
    sections: ["\\bfees?\\b", "expenses?", "compensation", "carried interest", "incentive", "performance (fee|allocation)", "servicing", "sales load|commission", "placement", "platform", "feeder", "administration", "borrowings|leverage"]
  keywords: [management fee, platform fee, administration fee, servicing fee, feeder, incentive fee, performance fee, hurdle, catch-up, subscription fee, placement fee, sales load, expense ratio]
  rules: "Quote each fee layer with its rate, every place it appears, so the documents can be compared. When the fund offers several share classes, quote only the class with the lowest recurring fees that individual investors can buy, and name the class in the value."
  fields:
    - { name: management_fee, recurring: true, description: "Management fee percent" }
    - { name: platform_fee, recurring: true, description: "Platform fee percent" }
    - { name: administration_fee, recurring: true, description: "Administration fee percent" }
    - { name: feeder_charge, recurring: true, description: "The feeder's own charge, percent" }
    - { name: servicing_fee, recurring: true, description: "Servicing or distribution fee the share class requires, percent" }
    - { name: optional_servicing_fee, description: "Servicing fee the investor may decline (noted, not counted)" }
    - { name: incentive_fee, description: "Incentive or performance fee: rate, hurdle and catch-up (noted, not counted)" }
    - { name: upfront_fee, description: "Upfront, subscription or placement fee (noted, not counted)" }
    - { name: fund_expenses, description: "Fund operating expenses or their cap (noted, not counted)" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` state a rate for the management fee and for every other recurring fee layer they mention (platform fee, administration fee, the feeder's own charge, a servicing fee the share class requires)?" }
derive:
  - { if: "fees_disagree", then: Incomplete }   # a counted layer is quoted at two rates (B6)
  - { if: "sufficient < 0.7", then: Incomplete }
  - { then: Pass }   # no threshold: cost alone never fails a fund (B1)
flags:
  - { if: "fees_disagree", flag: Fee rates disagree across documents }
$yaml$),
('operability', $yaml$id: operability
version: 3
extractor:
  sources:
    doc_types: [terms, offering document, governing agreement, ddq, policies/compliance, deck]
    sections: ["administrator", "auditor|accountants?", "valuation", "custod", "transfer agent", "net asset value|\\bnav\\b", "service providers?", "affiliat"]
  keywords: [administrator, auditor, valuation policy, custodian, custody, independent valuation, NAV, affiliate]
  rules: "Quote who serves as administrator, auditor and custodian, any relationship between the administrator and the manager, and where the valuation policy is described."
  fields:
    - { name: administrator, description: "Fund administrator, and any affiliation with the manager" }
    - { name: auditor, description: "Independent auditor" }
    - { name: valuation_policy, description: "Written valuation policy" }
    - { name: custody, description: "Custodian, or how the position is held" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` name the fund's administrator and an independent auditor?" }
  - { id: affiliated_admin, type: bool, q: "Is the administrator in `facts.administrator` the manager itself or affiliated with the manager, such as a parent, subsidiary or company under common control?" }
  - { id: has_valuation_policy, type: bool, q: "Do `facts` show that the fund has a written valuation policy?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { if: "affiliated_admin >= 0.7", then: Incomplete }   # C1
  - { if: "has_valuation_policy < 0.7", then: Incomplete }   # C2: until it is received
  - { then: Pass }   # a Fail comes only from the analyst's custody and pricing check (C4)
flags:
  - { if: "affiliated_admin >= 0.7", flag: Affiliated administrator }
  - { flag: "Custody and pricing: analyst to check" }   # a manual line on every screen (C3)
$yaml$),
('track_record', $yaml$id: track_record
version: 3
extractor:
  sources:
    doc_types: [track record, deck, offering document, ddq]
    sections: ["track record", "performance", "returns?", "prior (funds?|investments|experience)", "investment (history|experience|results)", "composite", "predecessor"]
    whole_docs_under: 12
  keywords: [net IRR, gross IRR, net return, gross return, since inception, track record, performance, TVPI, MOIC, predecessor, prior firm]
  rules: "Quote performance statements. Say whether each is net or gross, fund level or deal level, and whose record it is, only if the page says so."
  fields:
    - { name: net_return, description: "Net return or net IRR stated" }
    - { name: gross_return, description: "Gross return stated" }
    - { name: fund_level_record, description: "Fund-level performance since inception" }
    - { name: record_source, description: "Whose record it is: this manager's fund, a predecessor fund, or the team at a prior employer" }
    - { name: record_fees, description: "The fees the record is stated net of, when the documents give them" }
questions:
  - { id: sufficient, type: bool, q: "Does `facts` contain any historical fund return, such as an IRR, multiple or percentage return?" }
  - { id: basis, type: choice, q: "Does `facts` state the fund's historical return as net of fees, as gross of fees, or not at all?", options: [net, gross, not_stated], criteria: { net: "A return explicitly stated net of fees and expenses", gross: "A return stated gross, or a return with no net designation", not_stated: "No historical return appears in the facts" } }
  - { id: fund_level, type: bool, q: "Is the return in `facts` a fund-level record (a whole fund's performance since inception) rather than deal-by-deal results?" }
  - { id: prior_employer, type: bool, q: "Was the record in `facts` earned by the team at a prior employer rather than by this manager?" }
  - { id: lighter_fees, type: bool, q: "Is the record in `facts` stated net of lower fees than this fund charges?" }
derive:
  - { if: "sufficient >= 0.7 and basis == 'net' and fund_level >= 0.7 and prior_employer < 0.7 and lighter_fees < 0.7", then: Pass }
  - { then: Incomplete }   # never fails (D1, D2): deal-level, gross, prior-employer or missing records stay open
flags:
  - { if: "sufficient >= 0.7 and lighter_fees >= 0.7", flag: "Restate the record at this fund's fees" }   # D3
  - { if: "sufficient >= 0.7 and (basis != 'net' or fund_level < 0.7 or prior_employer >= 0.7)", flag: "RWP pro forma possible" }   # D1
$yaml$)
) as v(id, yaml)
where g.id = v.id;
