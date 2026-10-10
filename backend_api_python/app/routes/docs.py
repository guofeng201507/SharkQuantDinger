"""Per-locale product documentation endpoints (in-app user guide).

Endpoints:
- GET  /api/docs            - inventory of stored editions (no bodies)
- GET  /api/docs/<slug>     - one document, localized by X-App-Lang
- PUT  /api/docs/<slug>     - create/replace an edition (requires `settings`)
"""
from __future__ import annotations

from flask import g, jsonify, request
from app.openapi.blueprint import HumanBlueprint as Blueprint

from app.services.docs_service import DocError, get_doc, list_docs, upsert_doc
from app.utils.auth import login_required, permission_required
from app.utils.language import detect_request_language
from app.utils.logger import get_logger

logger = get_logger(__name__)

docs_blp = Blueprint('docs', __name__)


@docs_blp.route('', methods=['GET'])
@login_required
def list_documentation():
    """Which documents and editions are stored."""
    try:
        return jsonify({'code': 1, 'msg': 'success', 'data': list_docs()})
    except Exception as e:
        logger.error("list_documentation failed: %s", e)
        return jsonify({'code': 0, 'msg': str(e), 'data': []}), 500


@docs_blp.route('/<slug>', methods=['GET'])
@login_required
def get_documentation(slug: str):
    """Return the document for the caller's UI language (any edition as fallback)."""
    try:
        doc = get_doc(slug, detect_request_language(request))
        if not doc:
            return jsonify({'code': 0, 'msg': 'document not found', 'data': None}), 404
        return jsonify({'code': 1, 'msg': 'success', 'data': doc})
    except Exception as e:
        logger.error("get_documentation failed slug=%s: %s", slug, e)
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@docs_blp.route('/<slug>', methods=['PUT'])
@login_required
@permission_required('settings')
def save_documentation(slug: str):
    """Create or replace one edition. Body: {content_md, locale?, title?}."""
    body = request.get_json(silent=True) or {}
    try:
        result = upsert_doc(
            slug,
            body.get('locale') or detect_request_language(request),
            body.get('content_md', ''),
            title=body.get('title'),
            user_id=getattr(g, 'user_id', None),
        )
        return jsonify({'code': 1, 'msg': 'saved', 'data': result})
    except DocError as exc:
        return jsonify({'code': 0, 'msg': exc.message, 'data': None}), exc.http
    except Exception as e:
        logger.error("save_documentation failed slug=%s: %s", slug, e)
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500
