import os
import json
import imaplib
import smtplib
import email
from email.message import EmailMessage
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import quote
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from openai import OpenAI  # ✅ Correct import for new OpenAI client

# =================== Load environment variables ===================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY is not set in environment variables.")

# ✅ Create OpenAI v1 client
client = OpenAI(api_key=OPENAI_API_KEY)

# =================== Load Listings ===================
with open("listings.json", "r", encoding="utf-8") as f:
    listings_data = json.load(f)

# =================== Load Knowledge Vectorstore ===================
embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
vectorstore = FAISS.load_local(
    "guest_kb_vectorstore", embeddings, allow_dangerous_deserialization=True
)

# =================== Utility Functions ===================
def generate_airbnb_link(area, checkin, checkout, adults=2, children=0, infants=0, pets=0):
    area_encoded = quote(area)
    return (
        f"https://www.airbnb.com/s/Cairo--{area_encoded}/homes"
        f"?checkin={checkin}&checkout={checkout}"
        f"&adults={adults}&children={children}&infants={infants}&pets={pets}"
    )

def get_prompt():
    return """
You are a professional, friendly, and detail-oriented guest experience assistant working for a short-term rental company in Cairo, Egypt.

Always help with questions related to vacation stays, Airbnb-style bookings, and guest policies.

Only ignore a question if it's completely unrelated to travel (e.g., programming, politics, etc).

Use the internal knowledge base provided to answer questions clearly and accurately. Be warm and helpful.
"""

def find_matching_listings(city, guests):
    results = []
    for listing in listings_data:
        if listing["city_hint"].lower() == city.lower() and listing["guests"] >= guests:
            url = listing.get("url") or f"https://anqakhans.holidayfuture.com/listings/{listing['id']}"
            results.append(f"{listing['name']} (⭐ {listing['rating']})\n{url}")
        if len(results) >= 3:
            break
    return results

# =================== Generate AI Response ===================
def generate_response(user_message):
    today = datetime.today().date()
    checkin = today + timedelta(days=3)
    checkout = today + timedelta(days=6)

    relevant_docs = vectorstore.similarity_search(user_message, k=3)
    kb_context = "\n\n".join([doc.page_content for doc in relevant_docs])

    links = {
        "Zamalek": generate_airbnb_link("Zamalek", checkin, checkout),
        "Maadi": generate_airbnb_link("Maadi", checkin, checkout),
        "Garden City": generate_airbnb_link("Garden City", checkin, checkout),
    }
    custom_links = "\n".join([f"[Explore {k}]({v})" for k, v in links.items()])

    listings = find_matching_listings("Cairo", 5)
    suggestions = "\n\nHere are some great options for you:\n" + "\n".join(listings) if listings else ""

    response = client.chat.completions.create(  # ✅ Updated to use OpenAI v1 client
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": f"{get_prompt()}\n\nUse this context if helpful:\n{kb_context}\n\n{custom_links}\n{suggestions}"
            },
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()

# =================== Email Send/Receive ===================
def send_email(to_email, subject, body):
    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = f"Re: {subject}"
    msg.set_content(body)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)

def check_email():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    mail.select("inbox")

    status, messages = mail.search(None, '(UNSEEN)')
    for num in messages[0].split():
        typ, msg_data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        from_email = email.utils.parseaddr(msg["From"])[1]
        subject = msg["Subject"]
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
        else:
            body = msg.get_payload(decode=True).decode()

        print(f"📩 Received from {from_email}: {subject}")
        try:
            reply = generate_response(body)
            send_email(from_email, subject, reply)
            print("✅ Replied.")
        except Exception as e:
            print("❌ Error:", e)

    mail.logout()

# =================== Start Bot ===================
if __name__ == "__main__":
    print("📧 Email bot started. Listening for new messages...")
    while True:
        check_email()
