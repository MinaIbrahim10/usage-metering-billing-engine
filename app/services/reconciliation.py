import logging
import time

import stripe
from sqlalchemy import select

from app.core.config import STRIPE_SECRET_KEY
from app.db.session import SessionLocal
from app.models import Subscription


logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY


def reconcile_subscription(
    subscription_id: int,
    max_attempts: int = 3,
) -> None:
    """
    Reconcile one local subscription against Stripe.

    Runs outside the request path.
    Retries transient failures and logs a final failure.
    """

    for attempt in range(1, max_attempts + 1):
        db = SessionLocal()

        try:
            subscription = db.scalar(
                select(Subscription).where(
                    Subscription.id == subscription_id
                )
            )

            if subscription is None:
                logger.error(
                    "Reconciliation failed: subscription %s not found",
                    subscription_id,
                )
                return

            if not subscription.stripe_subscription_id:
                logger.info(
                    "Subscription %s has no Stripe subscription ID; skipping",
                    subscription_id,
                )
                return

            stripe_subscription = stripe.Subscription.retrieve(
                subscription.stripe_subscription_id
            )

            stripe_status = stripe_subscription.status

            if subscription.status != stripe_status:
                subscription.status = stripe_status
                db.commit()

            logger.info(
                "Reconciliation succeeded for subscription %s",
                subscription_id,
            )
            return

        except stripe.StripeError as exc:
            db.rollback()

            logger.warning(
                "Reconciliation attempt %s/%s failed for subscription %s: %s",
                attempt,
                max_attempts,
                subscription_id,
                exc,
            )

            if attempt == max_attempts:
                logger.error(
                    "Reconciliation permanently failed for subscription %s",
                    subscription_id,
                )
                return

            time.sleep(attempt)

        except Exception:
            db.rollback()

            logger.exception(
                "Unexpected reconciliation failure for subscription %s",
                subscription_id,
            )
            return

        finally:
            db.close()
