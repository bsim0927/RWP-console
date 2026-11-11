-- Total annual cost screens one share class (decision B5): the analyst's choice from intake, otherwise the
-- cheapest class individual investors can buy. Other classes are noted, not counted. The live gate is kept in
-- gate_history first and the new definition becomes the next version, as a console edit would.

insert into public.gate_history (gate_id, position, yaml, version, reason)
select id, position, yaml, version, 'edit' from public.gates where id = 'total_annual_cost';

update public.gates g
set version = g.version + 1,
    yaml = regexp_replace($yaml$id: total_annual_cost
version: 4
extractor:
  sources:
    doc_types: [terms, offering document, governing agreement, ddq, deck]
    sections: ["\\bfees?\\b", "expenses?", "compensation", "carried interest", "incentive", "performance (fee|allocation)", "servicing", "sales load|commission", "placement", "platform", "feeder", "administration", "share class|class [a-z]\\b", "borrowings|leverage"]
  keywords: [management fee, platform fee, administration fee, servicing fee, feeder, incentive fee, performance fee, hurdle, catch-up, subscription fee, placement fee, sales load, expense ratio, share class]
  rules: "Quote each fee layer with its rate, every place it appears, so the documents can be compared. Screen one share class: the one the analyst chose if given, otherwise the class with the lowest recurring fees that individual investors can buy; name it in each value. Record every other class, with its recurring fees, as other_share_classes."
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
    - { name: other_share_classes, description: "Each share class not screened, with its recurring fees (noted, not counted)" }
questions:
  - { id: sufficient, type: bool, q: "Do `facts` state a rate for the management fee and for every other recurring fee layer they mention (platform fee, administration fee, the feeder's own charge, a servicing fee the share class requires)?" }
derive:
  - { if: "fees_disagree", then: Incomplete }   # a counted layer is quoted at two rates (B6)
  - { if: "sufficient < 0.7", then: Incomplete }
  - { then: Pass }   # no threshold: cost alone never fails a fund (B1)
flags:
  - { if: "fees_disagree", flag: Fee rates disagree across documents }
$yaml$, '^version: \d+', 'version: ' || (g.version + 1), 'n'),
    updated_at = now()
where g.id = 'total_annual_cost';
