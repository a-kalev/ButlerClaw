from claw import ClawTask, ClawResult, ClawSection, ClawItem, ClawAction
from brain import understand_task, pick_best
from search import search_kroger, refresh_kroger_token
from memory import load_profile, save_profile


class AutoCartTask(ClawTask):
    """
    Takes a user message, searches Kroger for best matches,
    and adds them directly to the user's cart.
    Requires valid kroger_access_token in profile.
    Token refresh is attempted automatically if expired.
    """
    task_type = "auto_cart"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        job_id = self._make_job_id()
        message = payload.get("message", "")
        profile = self._get_profile(user_id)

        # ── Auth check ────────────────────────────────────────────────────────
        access_token = profile.get("kroger_access_token")
        if not access_token:
            refresh_token = profile.get("kroger_refresh_token")
            if refresh_token:
                access_token, new_refresh = refresh_kroger_token(refresh_token)
                if access_token:
                    profile["kroger_access_token"] = access_token
                    if new_refresh:
                        profile["kroger_refresh_token"] = new_refresh
                    save_profile(user_id, profile)
            if not access_token:
                return ClawResult(
                    job_id=job_id,
                    task_type=self.task_type,
                    status="needs_auth",
                    summary="Please sign in to Kroger so the butler can add items to your cart.",
                    actions=[ClawAction(label="Sign in to Kroger", url="/kroger-login")]
                )

        # ── Profile context ───────────────────────────────────────────────────
        zip_code = profile.get("zip_code", "10001")
        location_id = profile.get("location_id")
        store_name = profile.get("store_name", "Kroger")

        # ── Understand what to buy ────────────────────────────────────────────
        raw_terms = understand_task(
            message,
            history=[],
            profile=profile,
            strict=True
        )

        # Normalize — strict mode returns list of dicts, chat mode returns list of strings
        terms = []
        for t in raw_terms:
            if isinstance(t, dict):
                terms.append({"term": t.get("term", ""), "quantity": t.get("quantity", 1)})
            else:
                terms.append({"term": t, "quantity": 1})

        # ── Search + pick best + add to cart ─────────────────────────────────
        from search import add_to_cart

        section = ClawSection(title="Added to Cart", type="cart_summary")
        added_count = 0
        failed_count = 0

        for item in terms:
            term = item["term"]
            quantity = item["quantity"]
            data = search_kroger(term, zip_code=zip_code, location_id=location_id)
            best = pick_best(message, term, data["results"], profile)
            if not best:
                continue

            upc = best.get("upc")
            if not upc:
                continue

            status_code, _ = add_to_cart(
                upc=upc,
                quantity=quantity,
                location_id=location_id,
                access_token=access_token
            )

            # Handle expired token mid-run
            if status_code == 401:
                refresh_token = profile.get("kroger_refresh_token")
                if refresh_token:
                    new_access, new_refresh = refresh_kroger_token(refresh_token)
                    if new_access:
                        profile["kroger_access_token"] = new_access
                        if new_refresh:
                            profile["kroger_refresh_token"] = new_refresh
                        save_profile(user_id, profile)
                        access_token = new_access
                        status_code, _ = add_to_cart(
                            upc=upc,
                            quantity=quantity,
                            location_id=location_id,
                            access_token=access_token
                        )

            added = status_code in (200, 201, 204)
            if added:
                added_count += 1
            else:
                failed_count += 1

            section.items.append(ClawItem(
                name=best.get("name", ""),
                price=best.get("sale_price") or best.get("regular_price"),
                sale=bool(best.get("sale_price")),
                image=best.get("image"),
                upc=upc,
                added=added,
                reason=best.get("reason", "")
            ))

        # ── Build result ──────────────────────────────────────────────────────
        if added_count == 0 and failed_count == 0:
            summary = "No matching products found for your request."
        elif failed_count == 0:
            summary = f"{added_count} item{'s' if added_count != 1 else ''} added to your {store_name} cart."
        else:
            summary = f"{added_count} added, {failed_count} failed. You may need to re-authenticate."

        return ClawResult(
            job_id=job_id,
            task_type=self.task_type,
            status="done",
            summary=summary,
            sections=[section],
            actions=[
                ClawAction(
                    label=f"View {store_name} Cart",
                    url="https://www.kroger.com/cart"
                )
            ]
        )
