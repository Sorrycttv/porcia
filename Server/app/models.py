from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sex: Mapped[str] = mapped_column(String(10), default="other")
    age: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    activity: Mapped[str] = mapped_column(String(20), default="moderate")
    goal: Mapped[str] = mapped_column(String(20), default="maintain")
    meals_per_day: Mapped[int] = mapped_column(Integer, default=3)
    diet: Mapped[str] = mapped_column(String(20), default="none")
    restrictions: Mapped[str] = mapped_column(Text, default="")
    preferred_foods: Mapped[str] = mapped_column(Text, default="")
    target_calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_budget: Mapped[float | None] = mapped_column(Float, nullable=True)


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    calories: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    carbs: Mapped[float] = mapped_column(Float)
    diet: Mapped[str] = mapped_column(String(20), default="none")
    allergens: Mapped[str] = mapped_column(Text, default="")
    ingredients: Mapped[str] = mapped_column(Text)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    preparation_minutes: Mapped[int] = mapped_column(Integer, default=20)
    instructions: Mapped[str] = mapped_column(Text, default="")
    meal_slot: Mapped[str] = mapped_column(String(20), default="main")
    side_dish: Mapped[str] = mapped_column(String(160), default="")
    batch_servings: Mapped[int] = mapped_column(Integer, default=1)
    storage_days: Mapped[int] = mapped_column(Integer, default=0)


class FridgeItem(Base):
    """A user-maintained inventory used by the shopping and recipe helpers."""

    __tablename__ = "fridge_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    product: Mapped[str] = mapped_column(String(100))
    grams: Mapped[float] = mapped_column(Float)


class MealPlan(Base):
    __tablename__ = "meal_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_date: Mapped[date] = mapped_column(Date)
    target_calories: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MealPlanItem(Base):
    __tablename__ = "meal_plan_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id", ondelete="CASCADE"), index=True)
    meal: Mapped[str] = mapped_column(String(30))
    recipe_name: Mapped[str] = mapped_column(String(160))
    portion_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    calories: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    carbs: Mapped[float] = mapped_column(Float)


class SavedPlan(Base):
    """The exact latest response shown in the mobile client."""

    __tablename__ = "saved_plans"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
