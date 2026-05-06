from claw import ClawTask, ClawResult, ClawSection, ClawItem, ClawAction
from brain import plan_meals, pick_best
from search import search_kroger, refresh_kroger_token
from memory import load_profile, save_profile


class MealPlannerTask(ClawTask):
    """
    Plans 5 dinners using one Groq call, deduplicates ingredients,
    searches Kroger for best matches, and returns a ClawResult ready
    for user review before adding to cart.
    Does NOT add to cart automatically — UI shows plan first.
    """
    task_type = "meal_planner"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        job_id = self._make_job_id()
        profile = self._get_profile(user_id)

        zip_code = profile.get("zip_code", "10001")
        location_id = profile.get("location_id")
        store_name = profile.get("store_name", "Kroger")

        # ── Step 1: Plan 5 meals (one Groq call) ─────────────────────────────
        meals = plan_meals(profile)
        if not meals:
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="failed",
                summary="Sorry, the butler couldn't generate a meal plan. Please try again."
            )

        # ── Step 2: Deduplicate ingredients across all meals ──────────────────
        # Map ingredient → list of meal indices that need it
        ingredient_to_meals = {}
        for meal_idx, meal in enumerate(meals):
            for ingredient in meal.get("ingredients", []):
                ingredient = ingredient.strip().lower()
                if ingredient not in ingredient_to_meals:
                    ingredient_to_meals[ingredient] = []
                ingredient_to_meals[ingredient].append(meal_idx)

        # ── Step 3: Search Kroger once per unique ingredient ──────────────────
        ingredient_to_product = {}
        for ingredient in ingredient_to_meals:
            data = search_kroger(ingredient, zip_code=zip_code, location_id=location_id)
            best = pick_best(ingredient, ingredient, data["results"], profile)
            if best:
                ingredient_to_product[ingredient] = best

        # ── Step 4: Build ClawSections — one per meal ─────────────────────────
        sections = []
        total_items = 0

        for meal in meals:
            section = ClawSection(
                title=f"{meal['day']} — {meal['meal']}",
                type="meal",
                recipe=meal.get("recipe", [])
            )
            for ingredient in meal.get("ingredients", []):
                ingredient_key = ingredient.strip().lower()
                product = ingredient_to_product.get(ingredient_key)
                if product:
                    section.items.append(ClawItem(
                        name=product.get("name", ""),
                        price=product.get("sale_price") or product.get("regular_price"),
                        sale=bool(product.get("sale_price")),
                        image=product.get("image"),
                        upc=product.get("upc", ""),
                        added=False,
                        reason=ingredient
                    ))
                    total_items += 1
            sections.append(section)

        # ── Step 5: Return plan for user review (no cart add yet) ────────────
        return ClawResult(
            job_id=job_id,
            task_type=self.task_type,
            status="done",
            summary=f"5 dinners planned — {len(ingredient_to_product)} ingredients found at {store_name}.",
            sections=sections,
            actions=[
                ClawAction(
                    label="Add All to Cart",
                    action="add_meal_plan_to_cart"
                ),
                ClawAction(
                    label=f"View {store_name} Cart",
                    url="https://www.kroger.com/cart"
                )
            ]
        )
