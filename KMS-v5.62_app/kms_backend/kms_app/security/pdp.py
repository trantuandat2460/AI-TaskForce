"""PDP — bộ quyết định quyền hợp nhất authorize() 8 bước (§7 v5.3).
Fail-closed, chặn sớm; trả Decision{allow, reason, effective, steps[]}.
steps[] để render decision-trace (mỗi bước: rule/status/detail)."""
from config.settings import CLASS_RANK, ROLE_KINDS

def _subset(req, have): return all(t in have for t in req)
def _role_allows(role, kind):
    k = ROLE_KINDS.get(role)
    return k == "*" or (k is not None and kind in k)

def member_of(subject, project): return bool(project) and project in subject["projects"]
def owns(subject, resource): return False
def manages(subject, person): return person in subject["manages"]

class Decision(dict):
    @property
    def allow(self): return self["allow"]
    @property
    def reason(self): return self["reason"]

def authorize(subject, resource, ctx=None):
    ctx = ctx or {}
    steps = []
    def add(rule, status, detail): steps.append({"rule": rule, "status": status, "detail": detail})

    if subject is None:
        add("DENY_AUTH", "deny", "không có chủ thể")
        return Decision(allow=False, reason="DENY_AUTH", effective=None, steps=steps)
    add("subject", "pass", f'{subject["user_id"]} · {subject["role"]} · {subject["clearance"]}')

    if resource.get("is_credential"):
        add("DENY_CREDENTIAL", "deny", "credential — chặn cứng (ranh giới 4)")
        return Decision(allow=False, reason="DENY_CREDENTIAL", effective=None, steps=steps)
    add("credential", "pass", "không phải credential")

    limit = ctx.get("requested_limit") or subject["clearance"]
    effective = subject["clearance"] if CLASS_RANK[subject["clearance"]] <= CLASS_RANK[limit] else limit
    add("effective", "pass", f"min(clearance,limit) = {effective}")

    if CLASS_RANK[effective] < CLASS_RANK[resource["data_class"]]:
        add("DENY_DCM", "deny", f'effective {effective} < {resource["data_class"]}')
        return Decision(allow=False, reason="DENY_DCM", effective=effective, steps=steps)
    add("DCM_gate", "pass", f'effective {effective} ≥ {resource["data_class"]}')

    req = resource.get("required_tags") or []
    if not _subset(req, subject["tags"]):
        miss = [t for t in req if t not in subject["tags"]]
        add("DENY_ABAC", "deny", "thiếu tag: " + ", ".join(miss))
        return Decision(allow=False, reason="DENY_ABAC", effective=effective, steps=steps)
    add("ABAC", "pass", ("tags ⊇ {" + ",".join(req) + "}") if req else "không yêu cầu tag")

    op = resource.get("owner_project")
    if op and not resource.get("is_personnel_report") and not member_of(subject, op) and not owns(subject, resource):
        add("DENY_PROJECT", "deny", f"không thuộc dự án {op}")
        return Decision(allow=False, reason="DENY_PROJECT", effective=effective, steps=steps)
    add("project_isolation", "pass" if op else "skip", (f"∈ dự án {op}") if op else "không gắn dự án")

    if resource.get("kind") == "FOUNDRY" and resource.get("owner_dept") \
       and subject["department"] != resource["owner_dept"] and subject["role"] != "ADMIN":
        add("DENY_DEPARTMENT", "deny", f'phòng {subject["department"]} ≠ {resource["owner_dept"]}')
        return Decision(allow=False, reason="DENY_DEPARTMENT", effective=effective, steps=steps)
    add("dept_scope", "pass" if resource.get("kind") == "FOUNDRY" else "skip",
        (f'phòng {resource.get("owner_dept")}') if resource.get("kind") == "FOUNDRY" else "không phải Foundry")

    if resource.get("is_personnel_report"):
        sp = resource.get("subject_person")
        if subject["user_id"] == sp: add("ReBAC_personnel", "pass", "chính mình")
        elif manages(subject, sp):   add("ReBAC_personnel", "pass", f'manages({subject["user_id"]}→{sp})')
        elif subject["role"] == "HR" and subject.get("hr_purpose"): add("ReBAC_personnel", "pass", "HR + hr_purpose")
        else:
            add("DENY_REBAC_PERSONNEL", "deny", "không self / không manages / không HR-purpose")
            return Decision(allow=False, reason="DENY_REBAC_PERSONNEL", effective=effective, steps=steps)
    else:
        add("ReBAC_personnel", "skip", "không phải hồ sơ nhân sự")

    if not _role_allows(subject["role"], resource.get("kind")):
        add("DENY_ROLE", "deny", f'vai trò {subject["role"]} không được loại {resource.get("kind")}')
        return Decision(allow=False, reason="DENY_ROLE", effective=effective, steps=steps)
    add("role_ceiling", "pass", f'vai trò {subject["role"]} cho phép {resource.get("kind")}')

    add("ALLOW", "allow", f"effective={effective}")
    return Decision(allow=True, reason="ALLOW", effective=effective, steps=steps)
