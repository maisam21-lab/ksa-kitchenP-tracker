# Customer requirements (from call — Wednesday, February 18)

## What they want

1. **Each tab = one facility**  
   Every facility that has kitchens should appear as its own tab on the tracker. Each facility is shown by itself (one tab per facility).

2. **Data source**  
   Pull from **SF Kitchen Data** and **SF Churn Data**, with **pivot tables connected** (same data/sources that feed the pivot tables).

3. **Access**  
   **Every AE (Account Executive) has the same access** to view the kitchens — no difference in what different AEs can see.

---

## Implied product shape

| Current | Target (per customer) |
|--------|------------------------|
| Tabs like "Kitchens", "Master Kitchens list", "SF Churn Data", "Area Data", etc. | Tabs = **facilities** (e.g. one tab per facility name) |
| One "Master Kitchens" view with facility filter | Each tab shows **one facility’s kitchens** only |
| RBAC: associate vs manager vs super_user | **Single AE role**: same access for all AEs to view all facility tabs |
| Data: Salesforce reports + optional Sheet | Data: **SF Kitchen Data** + **SF Churn Data** (pivot tables connected) |

---

## What we need to do (high level)

1. **Tabs = facilities**  
   - Get list of facilities (from SF Kitchen Data or Churn Data, or a config list).  
   - Render **one tab per facility**; each tab shows only that facility’s kitchens (filter by facility).

2. **Data**  
   - Keep (or add) ingestion from **SF Kitchen Data** and **SF Churn Data**.  
   - Ensure pivot logic (if any) uses the same sources — “pivot tables connected” means the tracker should use the same underlying SF data.

3. **Access**  
   - Treat all AEs the same: one role (e.g. `ae` or `associate_viewer`) that can see **all facility tabs** and the same kitchens. No per-AE or per-facility restriction.

4. **Optional**  
   - If “Master Kitchens” stays as a global view, it can be one extra tab (e.g. “All facilities”) or a separate section; confirm with customer.

---

## Open points to confirm with customer

- **Facility list:** Should the list of tabs (facilities) be **dynamic** from the data (all distinct facilities in SF Kitchen Data) or a **fixed list** they maintain (e.g. config or sheet)?
- **Pivot “connected”:** Do they mean (a) the tracker reads the same SF reports that feed their pivot tables, or (b) the tracker UI should show pivot-style views (e.g. matrix by facility × status)?
- **Non-AE roles:** Do managers/super users still need different access (e.g. Admin, Tools), or should everyone be “AE” for the main tracker view?
