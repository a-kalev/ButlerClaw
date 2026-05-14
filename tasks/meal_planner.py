from claw import ClawTask, ClawResult, ClawSection, ClawItem, ClawAction
from brain import plan_meals
from search import search_kroger
from memory import load_profile, save_profile

# Common pantry staples — skip pick_best for these, just take top Kroger result
# This saves significant Groq tokens
_COMMON_PANTRY = {
    "salt", "pepper", "black pepper", "olive oil", "vegetable oil", "butter",
    "garlic", "onion", "flour", "sugar", "water", "baking soda", "baking powder",
    "soy sauce", "vinegar", "hot sauce", "ketchup", "mustard", "mayonnaise",
    "cumin", "paprika", "oregano", "basil", "thyme", "rosemary", "cinnamon",
    "chili powder", "red pepper flakes", "bay leaves", "vanilla extract"
}


class MealPlannerTask(ClawTask):
    """
    Plans 1/3/5 dinners using one Groq call.
    - Accepts num_meals from payload (default 5)
    - Pantry-aware: skips ingredients user likely has from usuals
    - Skips pick_best for common pantry items (saves tokens)
    - Returns per-meal sections with items for selective cart add
    - Does NOT add to cart automatically
    """
    task_type = "meal_planner"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        job_id = self._make_job_id()
        profile = self._get_profile(user_id)

        zip_code = profile.get("zip_code", "10001")
        location_id = profile.get("location_id")
        store_name = profile.get("store_name", "Kroger")

        # ── Payload options ───────────────────────────────────────────────────
        num_meals = int(payload.get("num_meals", 5))
        if num_meals not in (1, 3, 5):
            num_meals = 5

        # ── Pantry awareness: usuals the user likely already has ──────────────
        usuals = profile.get("usuals_products", [])
        pantry_terms = [
            (p.get("term") or p.get("name", "")).lower()
            for p in usuals
            if p.get("term") or p.get("name")
        ]

        # ── Step 1: Plan meals (one Groq call) ───────────────────────────────
        meals = plan_meals(profile, num_meals=num_meals, pantry_items=pantry_terms)
        if not meals:
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="failed",
                summary="Sorry, the butler couldn't generate a meal plan. Please try again."
            )

        # ── Step 2: Identify pantry vs shopping ingredients ───────────────────
        # pantry_set = common staples + user's usuals
        pantry_set = _COMMON_PANTRY | set(pantry_terms)

        # ── Step 3: Deduplicate shopping ingredients across meals ─────────────
        all_shopping_ingredients = {}
        all_pantry_ingredients = {}

        for meal_idx, meal in enumerate(meals):
            for ingredient in meal.get("ingredients", []):
                key = ingredient.strip().lower()
                if key in pantry_set:
                    all_pantry_ingredients[key] = ingredient
                else:
                    if key not in all_shopping_ingredients:
                        all_shopping_ingredients[key] = ingredient

        # ── Step 4: Search Kroger for shopping ingredients ────────────────────
        # Skip pick_best entirely — take top Kroger result directly (saves tokens)
        ingredient_to_product = {}
        for key, ingredient in all_shopping_ingredients.items():
            data = search_kroger(ingredient, zip_code=zip_code, location_id=location_id, limit=3)
            results = data.get("results", [])
            if results:
                best = results[0]
                ingredient_to_product[key] = best

        # ── Step 5: Build ClawSections — one per meal ─────────────────────────
        sections = []
        meal_number = 1

        for meal in meals:
            meal_name = meal.get("meal", f"Meal {meal_number}")
            section = ClawSection(
                title=f"Meal {meal_number} — {meal_name}",
                type="meal",
                recipe=meal.get("recipe", [])
            )

            pantry_for_meal = []
            for ingredient in meal.get("ingredients", []):
                key = ingredient.strip().lower()
                if key in pantry_set:
                    pantry_for_meal.append(ingredient)
                    continue
                product = ingredient_to_product.get(key)
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

            # Store pantry items in section title as JSON suffix
            # UI will parse this to show "you likely have" section
            if pantry_for_meal:
                import json
                section.title = section.title + f"|||{json.dumps(pantry_for_meal)}"

            sections.append(section)
            meal_number += 1

        total_shopping = len(ingredient_to_product)
        return ClawResult(
            job_id=job_id,
            task_type=self.task_type,
            status="done",
            summary=f"{num_meals} dinner{'s' if num_meals > 1 else ''} planned — {total_shopping} ingredients to add at {store_name}.",
            sections=sections,
            actions=[
                ClawAction(
                    label=f"View {store_name} Cart",
                    url="https://www.kroger.com/cart"
                )
            ]
        )
