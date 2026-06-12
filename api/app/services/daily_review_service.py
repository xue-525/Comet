"""每日回顾业务服务：汇总当日新增对话/记忆/文档，LLM 生成简报。

双触发：用户打开仪表盘时按需生成（当天没有则现生成）；Celery beat 每日定时批量生成。
"""
import asyncio
import uuid
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dashboard.prompt_renderer import render_prompt
from app.core.logging import get_logger
from app.models.conversation_model import ROLE_USER, Conversation, Message
from app.models.daily_review_model import DailyReview
from app.models.document_model import Document
from app.models.memory_model import Memory
from app.models.play_history_model import PlayHistory

logger = get_logger(__name__)


class DailyReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _day_range(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        return start, end

    async def _collect(self, user_id: uuid.UUID, day: date) -> dict:
        """收集当日新增的对话提问 / 主动记住 / 文档。"""
        start, end = await self._day_range(day)

        # 用户提问消息（关联本人会话）
        msg_rows = await self.session.execute(
            select(Message.content)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.user_id == user_id,
                Message.role == ROLE_USER,
                Message.created_at >= start,
                Message.created_at <= end,
            )
            .limit(30)
        )
        messages = [r[0] for r in msg_rows.all()]

        mem_rows = await self.session.execute(
            select(Memory.raw_text).where(
                Memory.user_id == user_id,
                Memory.created_at >= start,
                Memory.created_at <= end,
            )
        )
        memories = [r[0] for r in mem_rows.all()]

        doc_rows = await self.session.execute(
            select(Document.file_name).where(
                Document.user_id == user_id,
                Document.created_at >= start,
                Document.created_at <= end,
            )
        )
        documents = [r[0] for r in doc_rows.all()]

        # 今天听的歌（去重歌名，保留顺序）
        song_rows = await self.session.execute(
            select(PlayHistory.title, PlayHistory.artist)
            .where(
                PlayHistory.user_id == user_id,
                PlayHistory.played_at >= start,
                PlayHistory.played_at <= end,
            )
            .order_by(PlayHistory.played_at.asc())
        )
        seen: set[str] = set()
        songs: list[str] = []
        for title, artist in song_rows.all():
            label = f"{title}（{artist}）" if artist else title
            if label not in seen:
                seen.add(label)
                songs.append(label)

        return {
            "messages": messages,
            "memories": memories,
            "documents": documents,
            "songs": songs,
        }

    async def _collect_mood(self, user_id: uuid.UUID) -> str:
        """取今天的情绪画像，转成给 LLM 的一句话描述；无数据返回空串。"""
        try:
            from app.services.emotion_service import EmotionService

            data = await EmotionService(self.session).trend(user_id, 1)
            points = data.get("points", [])
            if not points:
                return ""
            today = points[-1]
            if (today.get("count") or 0) <= 0:
                return ""
            v = today.get("avg_valence", 0.0)
            if v >= 0.3:
                tone = "整体偏积极愉悦"
            elif v <= -0.3:
                tone = "情绪略低落"
            else:
                tone = "情绪比较平稳"
            return f"{tone}（效价 {v:.2f}，共 {today.get('count')} 条情绪记录）"
        except Exception as e:
            logger.warning("收集每日心情失败（忽略）: %s", e)
            return ""

    async def _generate_content(
        self, user_id: uuid.UUID, data: dict
    ) -> str:
        """调用对话模型生成简报；无模型或失败则用规则兜底。"""
        from app.core.llm.resolver import get_optional_client_for_type

        songs = data.get("songs", [])
        total = (
            len(data["messages"])
            + len(data["memories"])
            + len(data["documents"])
            + len(songs)
        )
        if total == 0:
            return "今天还没有新动态，休息一下也很好 🌿"

        mood = await self._collect_mood(user_id)

        client = await get_optional_client_for_type(self.session, user_id, "chat")
        fallback = (
            f"今天有 {len(data['messages'])} 次提问、"
            f"记住了 {len(data['memories'])} 件事、"
            f"新增了 {len(data['documents'])} 份文档、"
            f"听了 {len(songs)} 首歌。"
        )
        if not client:
            return fallback
        prompt = render_prompt(
            "daily_review.jinja2",
            messages="；".join(data["messages"][:20]) or "（无）",
            memories="；".join(data["memories"][:30]) or "（无）",
            documents="、".join(data["documents"]) or "（无）",
            song_count=len(songs),
            songs="、".join(songs[:20]) or "（无）",
            mood=mood or "（暂无情绪数据）",
        )
        # 关键调用做有限重试：模型偶发返回空（输出进 reasoning / token 不足）时再试一次
        for attempt in range(2):
            try:
                text = await client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=1200,
                )
                if text and text.strip():
                    return text.strip()
                logger.warning("每日回顾生成内容为空（第 %d 次）", attempt + 1)
            except Exception as e:
                logger.warning("每日回顾生成失败（第 %d 次）: %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(0.6)  # 轻微退避后重试一次
        logger.warning("每日回顾两次均未生成有效内容，用兜底文案")
        return fallback

    async def _generate_care(self, user_id: uuid.UUID, data: dict) -> str:
        """生成一句前瞻关怀/提醒（消费情绪 + 洞察 + 记忆）。失败返回空串。"""
        from app.core.llm.resolver import get_optional_client_for_type

        client = await get_optional_client_for_type(self.session, user_id, "chat")
        if not client:
            return ""
        try:
            mood = await self._collect_mood(user_id)
            insights = await self._collect_insights(user_id)
            recent_parts = (data.get("messages") or [])[:5]
            recent = "；".join(recent_parts) or "（无）"
            memories = "；".join((data.get("memories") or [])[:10]) or "（无）"
            prompt = render_prompt(
                "daily_care.jinja2",
                mood=mood or "（暂无情绪数据）",
                insights=insights or "（暂无）",
                memories=memories,
                recent=recent,
            )
            text = await client.chat(
                [{"role": "user", "content": prompt}], temperature=0.8, max_tokens=200
            )
            return (text or "").strip().strip('"「」') if text else ""
        except Exception as e:
            logger.warning("生成关怀句失败（忽略）: user=%s err=%s", user_id, e)
            return ""

    async def _collect_insights(self, user_id: uuid.UUID) -> str:
        """取「AI 眼中的你」高层洞察，拼成一句话；无则空串。"""
        try:
            from app.repositories.neo4j.memory_graph_repository import (
                MemoryGraphRepository,
            )

            rows = await MemoryGraphRepository().list_insights(str(user_id))
            contents = [
                (r.get("content") or "").strip() for r in rows[:3]
            ]
            return "；".join(c for c in contents if c)
        except Exception as e:
            logger.warning("收集洞察失败（忽略）: %s", e)
            return ""

    async def get_or_generate(self, user_id: uuid.UUID, day: date | None = None) -> dict:
        """生成/刷新当天回顾。

        每次进入仪表盘都按当前最新活动重新采集：
        - 当天数据有变化（统计数变了）就重新生成并覆盖；
        - 数据没变则复用已有回顾，避免重复调用 LLM。
        """
        day = day or date.today()
        existing = await self.session.scalar(
            select(DailyReview).where(
                DailyReview.user_id == user_id, DailyReview.review_date == day
            )
        )

        data = await self._collect(user_id, day)
        stats = {
            "messages": len(data["messages"]),
            "memories": len(data["memories"]),
            "documents": len(data["documents"]),
            "songs": len(data.get("songs", [])),
        }

        if (
            existing
            and existing.content
            and existing.content.strip()
            and self._same_stats(existing.stats, stats)
        ):
            # 已有非空回顾且活动数据无变化，直接复用，不重复调用 LLM
            return self.to_out_dict(existing)

        content = await self._generate_content(user_id, data)
        care = await self._generate_care(user_id, data)
        if existing:
            existing.content = content
            existing.care = care
            existing.stats = stats
            await self.session.commit()
            await self.session.refresh(existing)
            return self.to_out_dict(existing)

        review = DailyReview(
            user_id=user_id, review_date=day, content=content, care=care, stats=stats
        )
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return self.to_out_dict(review)

    @staticmethod
    def _same_stats(old: dict | None, new: dict) -> bool:
        old = old or {}
        return all(
            int(old.get(k, 0) or 0) == int(new.get(k, 0) or 0)
            for k in ("messages", "memories", "documents", "songs")
        )

    @staticmethod
    def to_out_dict(review: DailyReview) -> dict:
        return {
            "date": review.review_date.isoformat(),
            "content": review.content,
            "care": review.care or "",
            "stats": review.stats,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        }


__all__ = ["DailyReviewService"]
