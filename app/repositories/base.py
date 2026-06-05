from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class BaseRepository[ModelT]:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
