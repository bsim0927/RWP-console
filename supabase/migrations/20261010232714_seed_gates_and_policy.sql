-- Seed: the five screening gates and the disposition policy, exactly as they stood in gates/*.yaml and
-- policy.yaml when configuration moved into the database. Later changes are made in the console.

insert into public.gates (id, position, version, yaml) values ('investor_eligibility', 1, 2, $yaml$id: investor_eligibility
version: 2
extractor:
  sources:   # document types in priority order, then section-title patterns
    doc_types: [terms, offering document, subscription, ddq, governing agreement, deck]
    sections: ["minimum (initial )?(purchase|investment|commitment|subscription)", "suitability", "prospective investors", "eligib", "investor (qualification|standard|requirements)", "accredited", "qualified (purchaser|client)", "^the offering$", "unregistered securities"]
  keywords: [accredited investor, qualified purchaser, minimum investment, 3(c)(7), 3(c)(1), suitability, eligible investor]
  rules: "Quote the sentence that states who may invest and the minimum."
  fields:
    - { name: investor_standard, description: "Who may invest: accredited investor, qualified purchaser, institutional" }
    - { name: minimum_investment, description: "Minimum initial investment" }
    - { name: exemption, description: "Fund exemption, e.g. 3(c)(7)" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` state both who may invest in the fund and the minimum investment amount?" }
  - { id: qp_only, type: bool, q: "Does `facts.investor_standard` limit the fund to qualified purchasers or institutions only, excluding ordinary accredited investors?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { if: "qp_only >= 0.7", then: Fail }
  - { then: Pass }
$yaml$);
insert into public.gates (id, position, version, yaml) values ('total_annual_cost', 2, 2, $yaml$id: total_annual_cost
version: 2
extractor:
  sources:
    doc_types: [terms, offering document, governing agreement, ddq, deck]
    sections: ["\\bfees?\\b", "expenses?", "compensation", "carried interest", "incentive", "performance (fee|allocation)", "servicing", "sales load|commission", "borrowings|leverage"]
  keywords: [management fee, performance fee, incentive fee, servicing fee, hurdle, administration fee, expense ratio, subscription fee, sales load]
  rules: "Quote each fee layer with its percentage."
  fields:
    - { name: management_fee, recurring: true, description: "Management fee percent" }
    - { name: servicing_fee, recurring: true, description: "Distribution or servicing fee percent" }
    - { name: admin_expenses, recurring: true, description: "Administration or operating expenses percent" }
    - { name: incentive_fee, description: "Performance or incentive fee and hurdle" }
    - { name: upfront_load, description: "Subscription fee or sales load" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` disclose both a management fee and an incentive or performance fee?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { if: "total_pct is not None and total_pct > 3.0", then: Route with disclosure }  # placeholder threshold
  - { then: Pass }
$yaml$);
insert into public.gates (id, position, version, yaml) values ('operability', 3, 2, $yaml$id: operability
version: 2
extractor:
  sources:
    doc_types: [terms, offering document, governing agreement, ddq, policies/compliance, deck]
    sections: ["administrator", "auditor|accountants?", "valuation", "custod", "transfer agent", "net asset value|\\bnav\\b", "service providers?"]
  keywords: [administrator, auditor, valuation policy, custodian, custody, independent valuation, NAV]
  rules: "Quote who serves as administrator, auditor and custodian, and where the valuation policy is described."
  fields:
    - { name: administrator, description: "Third-party administrator" }
    - { name: auditor, description: "Independent auditor" }
    - { name: valuation_policy, description: "Written valuation policy" }
    - { name: custody, description: "Custody or platform availability" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` name an independent administrator, an independent auditor, and a written valuation policy?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { then: Pass }
$yaml$);
insert into public.gates (id, position, version, yaml) values ('track_record', 4, 2, $yaml$id: track_record
version: 2
extractor:
  sources:
    doc_types: [track record, deck, offering document, ddq]
    sections: ["track record", "performance", "returns?", "prior (funds?|investments|experience)", "investment (history|experience|results)", "composite"]
    whole_docs_under: 12
  keywords: [net IRR, gross IRR, net return, gross return, since inception, track record, performance, TVPI, MOIC]
  rules: "Quote performance statements. Say whether each is net or gross and fund level or deal level only if the page says so."
  fields:
    - { name: net_return, description: "Net return or net IRR stated" }
    - { name: gross_return, description: "Gross return stated" }
    - { name: fund_level_record, description: "Fund-level performance since inception" }
questions:
  - { id: sufficient, type: bool, q: "Does `facts` contain any historical fund return, such as an IRR, multiple or percentage return?" }
  - { id: basis, type: choice, q: "Does `facts` state the fund's historical return as net of fees, as gross of fees, or not at all?", options: [net, gross, not_stated], criteria: { net: "A return explicitly stated net of fees and expenses", gross: "A return stated gross, or a return with no net designation", not_stated: "No historical return appears in the facts" } }
derive:
  - { if: "basis == 'net' and sufficient >= 0.7", then: Pass }
  - { then: Fail }   # a deal-level, gross-only or absent record fails
$yaml$);
insert into public.gates (id, position, version, yaml) values ('disclosure_history', 5, 1, $yaml$id: disclosure_history
version: 1
# Not answerable from a data room. Needs Form ADV Part 1 Item 11 and BrokerCheck lookups.
static_result: Not yet run
$yaml$);
insert into public.policies (yaml) values ($yaml$# How gate results combine. Illustrative: the committee adopts the real thresholds.
# Ordered. First match wins. Conditions: any_fail, any_incomplete, any_review, otherwise.
# Incomplete outranks Fail because RWP's screens say "Under review" while any gate is open,
# even with a failed gate. Disclosure "Not yet run" counts as open.
rules:
  - when: any_review
    disposition: Under review (analyst to confirm one or more gates)
  - when: any_incomplete
    disposition: Under review (gates that cannot be closed are named)
  - when: any_fail
    disposition: Reviewed and not covered (draft, name the failed gate)
  - when: otherwise
    disposition: Coverable, subject to conditions
$yaml$);
