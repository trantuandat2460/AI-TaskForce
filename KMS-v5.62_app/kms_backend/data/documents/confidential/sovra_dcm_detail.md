---
doc_id: R-002
vsi_data_class: C3
vsi_corpus_id: corpus_c3
vsi_data_subclass: C3_CORE_IP
vsi_kind: SPEC_DETAIL
vsi_owner_project: SOVRA
vsi_required_tags: core-ip
vsi_sensitive_level: restricted
related: R-004
---
# Mô hình phân quyền DCM (chi tiết)
## Công thức
Mô hình DCM dùng effective = min(clearance, limit); fail-closed.
## PDP
PDP authorize() 8 bước: DCM gate → ABAC → cô lập dự án → scope phòng → ReBAC nhân sự → trần vai trò.
