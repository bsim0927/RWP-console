-- The CIO reviews every screen for now (decision G1); renamed or joined by analysts from the console.
insert into public.reviewers (id, name, role) values ('cio', 'CIO', 'cio') on conflict (id) do nothing;

-- Custody and pricing become the analyst's manual checks on operability (decisions C3, C4): a "no" fails the
-- gate. They replace the always-on reminder flag. The live gate is kept in gate_history first.
insert into public.gate_history (gate_id, position, yaml, version, reason)
select id, position, yaml, version, 'edit' from public.gates where id = 'operability';

update public.gates g
set version = g.version + 1,
    yaml = regexp_replace($yaml$id: operability
version: 4
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
  - { then: Pass }   # a Fail comes only from the analyst's checks below (C4)
flags:
  - { if: "affiliated_admin >= 0.7", flag: Affiliated administrator }
checks:   # answered by the analyst on every screen; a "no" fails the gate (C3, C4)
  - { id: custody, q: "Can the position be custodied?" }
  - { id: pricing, q: "Can the position be priced in RWP's reporting system?" }
$yaml$, '^version: \d+', 'version: ' || (g.version + 1), 'n'),
    updated_at = now()
where g.id = 'operability';
