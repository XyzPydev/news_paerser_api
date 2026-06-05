from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository


class NewsRepository(BaseRepository[object]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_recent(self) -> list[object]:
        return []
