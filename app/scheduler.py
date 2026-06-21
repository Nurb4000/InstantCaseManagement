import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def run_ola_sla_update(app):
    """Background job: update OLA/SLA for all active cases."""
    with app.app_context():
        from app import db
        from app.models import Case
        from app.ola import update_ola, get_ola_elapsed
        from app.sla import update_sla, get_sla_pct

        now = datetime.utcnow()
        cases = Case.query.filter(
            Case.status != 'resolved',
            Case.ola_started_at.isnot(None) | Case.sla_started_at.isnot(None)
        ).all()

        count = 0
        for case in cases:
            try:
                if case.ola_started_at is not None:
                    update_ola(case)
                if case.sla_started_at is not None:
                    update_sla(case)
                count += 1
            except Exception:
                logger.exception(f'Error updating OLA/SLA for case {case.id}')

        db.session.commit()
        logger.info(f'OLASLA update: checked {len(cases)} cases ({count} processed), {now}')
