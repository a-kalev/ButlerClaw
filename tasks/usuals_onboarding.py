from claw import ClawTask, ClawResult, ClawSection, ClawItem, ClawAction
from search import search_kroger

# Common staples to seed the onboarding picker.
# Grouped by category — each term maps to one Kroger search.
STAPLE_TERMS = [
    ("Dairy",       ["whole milk", "large eggs", "butter", "cheddar cheese", "greek yogurt"]),
    ("Bread",       ["sourdough bread", "whole wheat bread"]),
    ("Produce",     ["bananas", "roma tomatoes", "baby spinach", "garlic"]),
    ("Meat",        ["chicken breast", "ground beef", "bacon"]),
    ("Pantry",      ["olive oil", "pasta", "white rice", "canned tomatoes", "peanut butter"]),
    ("Beverages",   ["orange juice", "coffee"]),
]


class UsualsOnboardingTask(ClawTask):
    """
    Searches the user's store for common staples.
    Returns real products grouped by category for the onboarding UI picker.
    User taps products to add to their usuals list.
    Does NOT modify the profile — that happens via /usuals/add.
    """
    task_type = "usuals_onboarding"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        job_id = self._make_job_id()
        profile = self._get_profile(user_id)

        zip_code = profile.get("zip_code", "10001")
        location_id = profile.get("location_id")
        store_name = profile.get("store_name", "Kroger")

        if not location_id:
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="failed",
                summary="Please select your store first."
            )

        sections = []

        for category, terms in STAPLE_TERMS:
            section = ClawSection(title=category, type="onboarding")
            for term in terms:
                data = search_kroger(term, zip_code=zip_code, location_id=location_id, limit=1)
                results = data.get("results", [])
                if not results:
                    continue
                p = results[0]
                if not p.get("upc"):
                    continue
                section.items.append(ClawItem(
                    name=p.get("name", ""),
                    price=p.get("sale_price") or p.get("regular_price"),
                    sale=bool(p.get("sale_price")),
                    image=p.get("image"),
                    upc=p.get("upc", ""),
                    added=False,
                    reason=term   # term stored in reason — used as "term" when saving to usuals
                ))
            if section.items:
                sections.append(section)

        return ClawResult(
            job_id=job_id,
            task_type=self.task_type,
            status="done",
            summary=f"Here are common items available at {store_name}. Tap to add to your list.",
            sections=sections,
            actions=[
                ClawAction(label="Done", action="onboarding_complete")
            ]
        )
