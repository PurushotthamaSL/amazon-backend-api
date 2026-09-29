from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from jwt.exceptions import PyJWTError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Float, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, Mapped, mapped_column, relationship, sessionmaker

# ==========================================
# 1. DATABASE SETUP (SQLite)
# ==========================================
SQLALCHEMY_DATABASE_URL = "sqlite:///./amazon.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. DATABASE MODELS
# ==========================================
class DBUser(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password: Mapped[str] = mapped_column(String)

class DBProduct(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer)

class DBCartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    
    product = relationship("DBProduct")

class DBOrder(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    total_amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="PAID")

Base.metadata.create_all(bind=engine)

# ==========================================
# 3. FASTAPI APP & AUTH SETUP
# ==========================================
app = FastAPI(
    title="Amazon-style Backend API",
    description="A simplified e-commerce backend with Users, Products, Cart and Orders.",
    version="1.0.0"
)

# Redirect root http://127.0.0.1:8000/ directly to /docs
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

SECRET_KEY = "super-secret-key-change-this"
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(user_id: str):
    expire = datetime.now(timezone.utc) + timedelta(hours=2)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        user = db.scalar(select(DBUser).where(DBUser.id == user_id))
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

# ==========================================
# 4. PYDANTIC SCHEMAS
# ==========================================
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class ProductCreate(BaseModel):
    title: str
    description: str
    price: float = Field(gt=0)
    stock: int = Field(ge=0)

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    stock: Optional[int] = Field(default=None, ge=0)

class ProductOut(ProductCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)

class CartItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)

class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)

class CartItemOut(BaseModel):
    id: str
    product_id: str
    quantity: int
    product: ProductOut
    model_config = ConfigDict(from_attributes=True)

class OrderOut(BaseModel):
    id: str
    total_amount: float
    status: str
    model_config = ConfigDict(from_attributes=True)

# ==========================================
# 5. API ROUTES BY CATEGORY
# ==========================================

# --- HEALTH ---
@app.get("/health", tags=["Health"], summary="Health Check")
def health_check():
    return {"status": "ok"}

# --- AUTH ---
@app.post("/auth/register", tags=["Auth"], summary="Register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    if db.scalar(select(DBUser).where(DBUser.username == user.username)):
        raise HTTPException(status_code=400, detail="Username taken")
    new_user = DBUser(**user.model_dump())
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/auth/login", response_model=Token, tags=["Auth"], summary="Login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(DBUser).where(DBUser.username == form_data.username))
    if not user or user.password != form_data.password:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}

# --- PRODUCTS ---
@app.get("/products", response_model=List[ProductOut], tags=["Products"], summary="List Products")
def list_products(search: Optional[str] = None, db: Session = Depends(get_db)):
    stmt = select(DBProduct)
    if search:
        stmt = stmt.where(DBProduct.title.contains(search))
    return db.scalars(stmt).all()

@app.post("/products", response_model=ProductOut, tags=["Products"], summary="Create Product")
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    new_prod = DBProduct(**product.model_dump())
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)
    return new_prod

@app.get("/products/{product_id}", response_model=ProductOut, tags=["Products"], summary="Get Product")
def get_product(product_id: str, db: Session = Depends(get_db)):
    prod = db.scalar(select(DBProduct).where(DBProduct.id == product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return prod

@app.put("/products/{product_id}", response_model=ProductOut, tags=["Products"], summary="Update Product")
def update_product(product_id: str, updates: ProductUpdate, db: Session = Depends(get_db)):
    prod = db.scalar(select(DBProduct).where(DBProduct.id == product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, val in updates.model_dump(exclude_unset=True).items():
        setattr(prod, key, val)
    db.commit()
    db.refresh(prod)
    return prod

@app.delete("/products/{product_id}", tags=["Products"], summary="Delete Product")
def delete_product(product_id: str, db: Session = Depends(get_db)):
    prod = db.scalar(select(DBProduct).where(DBProduct.id == product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(prod)
    db.commit()
    return {"message": "Product deleted"}

# --- CART ---
@app.get("/cart", response_model=List[CartItemOut], tags=["Cart"], summary="View Cart")
def view_cart(user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(DBCartItem).where(DBCartItem.user_id == user.id)).all()

@app.post("/cart/items", tags=["Cart"], summary="Add Item")
def add_cart_item(item: CartItemCreate, user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    product = db.scalar(select(DBProduct).where(DBProduct.id == item.product_id))
    if not product or product.stock < item.quantity:
        raise HTTPException(status_code=400, detail="Product unavailable or insufficient stock")
    
    cart_item = DBCartItem(user_id=user.id, product_id=item.product_id, quantity=item.quantity)
    db.add(cart_item)
    db.commit()
    return {"message": "Item added to cart"}

@app.put("/cart/items/{item_id}", tags=["Cart"], summary="Update Item")
def update_cart_item(item_id: str, updates: CartItemUpdate, user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(DBCartItem).where(DBCartItem.id == item_id, DBCartItem.user_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in cart")
    item.quantity = updates.quantity
    db.commit()
    return {"message": "Cart item updated"}

@app.delete("/cart/items/{item_id}", tags=["Cart"], summary="Remove Item")
def remove_cart_item(item_id: str, user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(DBCartItem).where(DBCartItem.id == item_id, DBCartItem.user_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in cart")
    db.delete(item)
    db.commit()
    return {"message": "Item removed from cart"}

# --- ORDERS ---
@app.post("/orders/checkout", response_model=OrderOut, tags=["Orders"], summary="Checkout")
def checkout(user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    cart_items = db.scalars(select(DBCartItem).where(DBCartItem.user_id == user.id)).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    total = 0.0
    for item in cart_items:
        if item.product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for {item.product.title}")
        item.product.stock -= item.quantity
        total += item.product.price * item.quantity
    
    order = DBOrder(user_id=user.id, total_amount=round(total, 2))
    db.add(order)
    
    for item in cart_items:
        db.delete(item)
        
    db.commit()
    db.refresh(order)
    return order


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)