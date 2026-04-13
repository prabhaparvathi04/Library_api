from fastapi import FastAPI, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import importlib
import os

OpenAI = None
OpenAIError = Exception
client = None

try:
    openai_module = importlib.import_module("openai")
    OpenAI = getattr(openai_module, "OpenAI")
    OpenAIError = getattr(openai_module, "OpenAIError", Exception)
except ImportError:
    OpenAI = None
    OpenAIError = Exception

try:
    dotenv = importlib.import_module("dotenv")
    dotenv.load_dotenv()
except ImportError:
    pass

if OpenAI is not None:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class BookCreate(BaseModel):
    book_title: str
    author: str
    category: str
    isbn: str
    total_copies: int
    available_copies: int
    status: str


class ChatRequest(BaseModel):
    message: str
# ================= DATABASE =================
DATABASE_URL = "mysql+pymysql://root:0320@localhost/library_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

# ================= MODEL =================
class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    book_title = Column(String(100))
    author = Column(String(100))
    category = Column(String(100))
    isbn = Column(String(20))
    total_copies = Column(Integer)
    available_copies = Column(Integer)
    user_name = Column(String(100))
    user_email = Column(String(100))
    status = Column(String(20))

Base.metadata.create_all(bind=engine)

# ================= APP =================
app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ================= DB =================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def answer_from_book_data(message: str, books: list[Book]) -> str:
    if not books:
        return "No book records are available right now."

    def normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())

    msg = normalize(message)
    authors = sorted({b.author for b in books})
    titles = sorted({b.book_title for b in books})

    author_match = next((author for author in authors if normalize(author) in msg), None)
    title_match = next((title for title in titles if normalize(title) in msg), None)

    # try partial title match if exact substring doesn't work
    if not title_match:
        for title in titles:
            normalized_title = normalize(title)
            if all(word in msg for word in normalized_title.split() if len(word) > 2):
                title_match = title
                break

    if title_match:
        book = next(b for b in books if b.book_title == title_match)
        return (
            f"{book.book_title} by {book.author}: ISBN {book.isbn}, "
            f"total copies {book.total_copies}, available {book.available_copies}, status {book.status}."
        )

    if author_match:
        author_books = [b for b in books if b.author == author_match]
        parts = [
            f"'{b.book_title}' (ISBN {b.isbn}, total {b.total_copies}, available {b.available_copies}, status {b.status})"
            for b in author_books
        ]
        return f"Author {author_match} has {len(author_books)} book(s): " + ", ".join(parts) + "."

    if "author" in msg and ("detail" in msg or "details" in msg or "info" in msg):
        return "Authors include " + ", ".join(authors[:10]) + "."

    if "available" in msg or "copies" in msg:
        available_books = [b for b in books if b.available_copies > 0]
        if not available_books:
            return "No books are currently available."
        available_count = sum(b.available_copies for b in available_books)
        titles_list = ", ".join(b.book_title for b in available_books[:10])
        return (
            f"There are {len(available_books)} available titles with {available_count} available copies. "
            f"Examples: {titles_list}."
        )

    if "return" in msg or "returned" in msg:
        returned_books = [b for b in books if b.status.lower() == "returned"]
        if not returned_books:
            return "No books are currently marked as returned."
        titles_list = ", ".join(b.book_title for b in returned_books[:10])
        return f"Returned books: {titles_list}."

    if "total" in msg or "how many" in msg or "count" in msg or "number" in msg:
        if "category" in msg:
            counts = {}
            for b in books:
                counts[b.category] = counts.get(b.category, 0) + 1
            parts = [f"{cat}: {count}" for cat, count in counts.items()]
            return "Book count by category is " + ", ".join(parts) + "."
        total_copies = sum(b.total_copies for b in books)
        return f"There are {len(books)} titles and {total_copies} total copies in the database."

    if "category" in msg:
        categories = sorted({b.category for b in books})
        return "Categories available are " + ", ".join(categories) + "."

    if "author" in msg or "written by" in msg:
        return "Authors include " + ", ".join(authors[:10]) + "."

    if "title" in msg or "book" in msg or "name" in msg:
        titles_list = ", ".join(titles[:10])
        return f"Books include: {titles_list}."

    return "I can answer questions about book titles, authors, ISBNs, availability, returned books, total copies, and counts based on the current data."

# ================= HOME =================
@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    books = db.query(Book).all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"books": books}
    )
# ================= ADD BOOK =================
@app.post("/books")
def create_book(book: BookCreate, db: Session = Depends(get_db)):
    new_book = Book(**book.dict())
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    return new_book

@app.post("/books/form")
def add_book(
    book_title: str = Form(...),
    author: str = Form(...),
    category: str = Form(...),
    isbn: str = Form(...),
    total_copies: int = Form(...),
    available_copies: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    book = Book(
        book_title=book_title,
        author=author,
        category=category,
        isbn=isbn,
        total_copies=total_copies,
        available_copies=available_copies,
        status=status
    )
    db.add(book)
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/books/update/{book_id}")
def update_book_form(
    book_id: int,
    book_title: str = Form(...),
    author: str = Form(...),
    category: str = Form(...),
    isbn: str = Form(...),
    total_copies: int = Form(...),
    available_copies: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    book.book_title = book_title
    book.author = author
    book.category = category
    book.isbn = isbn
    book.total_copies = total_copies
    book.available_copies = available_copies
    book.status = status
    db.commit()
    return RedirectResponse("/", status_code=303)

# ================= BORROW =================
@app.get("/borrow/{book_id}")
def borrow_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.available_copies <= 0:
        raise HTTPException(status_code=400, detail="No copies available to borrow")

    book.available_copies -= 1
    book.status = "Borrowed"

    db.commit()
    return RedirectResponse("/", status_code=303)

# ================= GET BOOK =================
@app.get("/books/{book_id}")
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return book

# ================= UPDATE BOOK =================
@app.put("/books/{book_id}")
def update_book(book_id: int, book_data: BookCreate, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    for key, value in book_data.dict().items():
        setattr(book, key, value)

    db.commit()
    db.refresh(book)
    return book

# ================= RETURN =================
@app.get("/return/{book_id}")
def return_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(status_code=404, detail="Not Found")

    book.available_copies += 1
    book.status = "Returned"

    db.commit()
    return RedirectResponse("/", status_code=303)

# ================= DELETE =================
@app.get("/delete/{book_id}")
def delete(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()

    if book:
        db.delete(book)
        db.commit()

    return RedirectResponse("/", status_code=303)

# ================= API =================
@app.get("/books")
def get_books(db: Session = Depends(get_db)):
    return db.query(Book).all()


# ================= CHATBOT =================
@app.post("/chat-mini")
def chat_mini(request: ChatRequest, db: Session = Depends(get_db)):
    books = db.query(Book).all()

    data = [
        {
            "book_title": b.book_title,
            "author": b.author,
            "category": b.category,
            "isbn": b.isbn,
            "total_copies": b.total_copies,
            "available_copies": b.available_copies,
            "status": b.status,
        }
        for b in books
    ]

    prompt = f"""
You are a library database assistant.

Data:
{data}

Answer only using this data.
Keep it short.

Question: {request.message}
"""

    if client is None:
        local_response = answer_from_book_data(request.message, books)
        return {"response": local_response}

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"response": response.choices[0].message.content}
    except OpenAIError:
        local_response = answer_from_book_data(request.message, books)
        return {"response": local_response}
    except Exception:
        local_response = answer_from_book_data(request.message, books)
        return {"response": local_response}
