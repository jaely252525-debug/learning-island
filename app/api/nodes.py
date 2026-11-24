"""知识点接口：读完整内容、重新生成。PATCH（改名/合并/拆分）留给 M4。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_visitor
from ..db import get_session
from ..models import Document, Node, Visitor
from ..pipeline.generate import generate_contents
from ..schemas import NodeDetailOut
from . import compat

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def _own(db: Session, node_id: str, visitor: Visitor) -> tuple[Node, Document]:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    doc = db.get(Document, node.document_id)
    if doc is None or doc.visitor_id != visitor.id:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node, doc


def _detail(node: Node, db: Session) -> NodeDetailOut:
    content = node.content or {}
    plain = content.get("plain") or []
    nums = compat.number_map(db, node.document_id) if node.level == "knowledge" else {}
    return NodeDetailOut(
        id=node.id,
        parentId=node.parent_id,
        level=node.level,
        title=node.title,
        order=node.order_index,
        pageStart=node.page_start,
        pageEnd=node.page_end,
        status=node.status,
        locked=node.locked,
        prerequisites=list(node.prerequisites or []),
        sources=list(node.sources or []),
        content=node.content,
        game=node.game,
        questions=list(node.questions or []),
        importance=node.importance,
        quality=node.quality,
        num=nums.get(node.id),
        pg=compat.page_label(node.page_start, node.page_end) if node.page_start else None,
        o=content.get("original"),
        p=plain[1] if len(plain) > 1 else (plain[0] if plain else None),
        a=content.get("analogy"),
        svg=content.get("diagramSvg"),
        g=compat.game_for(node) if node.game else None,
        pre=[nums[p] for p in (node.prerequisites or []) if p in nums],
    )


@router.get("/{node_id}", response_model=NodeDetailOut)
def get_node(node_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    node, _ = _own(db, node_id, visitor)
    return _detail(node, db)


@router.post("/{node_id}/regenerate", response_model=NodeDetailOut)
def regenerate_node(node_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    node, doc = _own(db, node_id, visitor)
    if node.level != "knowledge":
        raise HTTPException(status_code=400, detail="只有知识点可以重新生成")
    if node.locked:
        raise HTTPException(status_code=409, detail="该节点已被用户编辑（locked），重新生成不会覆盖")
    generate_contents(db, doc, only_node=node.id, no_cache=True)
    db.refresh(node)
    return _detail(node, db)


@router.patch("/{node_id}")
def patch_node(node_id: str):
    raise HTTPException(status_code=501, detail="编辑接口（改名/合并/拆分/改前置）属于 M4，M2 未实现")
