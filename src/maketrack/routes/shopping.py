from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.project import ShoppingListRow
from maketrack.services import bom as bom_svc

router = APIRouter(tags=["shopping"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/api/shopping-list", response_model=list[ShoppingListRow])
async def shopping_list(session: SessionDep) -> list[ShoppingListRow]:
    return await bom_svc.shopping_list(session)
