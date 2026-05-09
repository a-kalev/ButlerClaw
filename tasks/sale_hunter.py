from claw import ClawTask, ClawResult, ClawSection, ClawItem
from search import search_kroger
from push import send_push
from memory import load_profile, save_profile


class SaleHunterTask(ClawTask):
    """
    Daily background task. Checks current Kroger prices for all usuals_products.
    If any are on sale, sends a push notification.
    Zero AI / zero Groq tokens — pure Kroger API.
    """
    task_type = "sale_hunter"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        job_id = self._make_job_id()
        profile = self._get_profile(user_id)

        # Guard: feature must be enabled
        sale_hunter_cfg = profile.get("claws", {}).get("sale_hunter", {})
        if not sale_hunter_cfg.get("enabled", False):
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="skipped",
                summary="Sale Hunter is disabled for this user."
            )

        usuals = profile.get("usuals_products", [])
        if not usuals:
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="skipped",
                summary="No usuals to check."
            )

        zip_code = profile.get("zip_code", "10001")
        location_id = profile.get("location_id")
        store_name = profile.get("store_name", "your store")

        on_sale = []

        for item in usuals:
            upc = item.get("upc")
            term = item.get("term") or item.get("name", "")
            if not upc or not term:
                continue

            data = search_kroger(term, zip_code=zip_code, location_id=location_id, limit=3)
            # Find the matching UPC in results
            for result in data.get("results", []):
                if result.get("upc") == upc:
                    sale_price = result.get("sale_price")
                    regular_price = result.get("regular_price")
                    if sale_price and sale_price != regular_price:
                        on_sale.append({
                            "upc": upc,
                            "name": item.get("name", ""),
                            "brand": item.get("brand", ""),
                            "image": item.get("image"),
                            "regular_price": regular_price,
                            "sale_price": sale_price,
                            "term": term
                        })
                        # Update stored price in profile
                        item["sale_price"] = sale_price
                    else:
                        item["sale_price"] = None
                    break

        # Save updated sale prices back to profile
        profile["usuals_products"] = usuals
        save_profile(user_id, profile)

        if not on_sale:
            return ClawResult(
                job_id=job_id,
                task_type=self.task_type,
                status="done",
                summary="No sales found on your usuals today."
            )

        # Build result section
        section = ClawSection(title="On Sale Today", type="sale_alert")
        for p in on_sale:
            section.items.append(ClawItem(
                name=p["name"],
                price=p["sale_price"],
                sale=True,
                image=p["image"],
                upc=p["upc"],
                added=False,
                reason=p.get("term", "")
            ))

        count = len(on_sale)
        names = ", ".join(p["name"].split()[0] for p in on_sale[:3])
        summary = f"🎉 {count} item{'s' if count > 1 else ''} on your list {'are' if count > 1 else 'is'} on sale at {store_name} today — {names}{'…' if count > 3 else ''}."

        # Send push notification
        push_sent = False
        subscription = profile.get("push_subscription")
        if subscription:
            push_sent = send_push(
                subscription=subscription,
                title="🎉 Sales on Your List!",
                body=summary,
                url="/?page=mylist"
            )

        return ClawResult(
            job_id=job_id,
            task_type=self.task_type,
            status="done",
            summary=summary,
            sections=[section],
            push_sent=push_sent
        )
