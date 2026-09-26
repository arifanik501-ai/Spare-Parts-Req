# MEP GROUP - Daily Floor Requisition Portal
### Automated ERP Scraper Bot & Spare Parts Tracking Dashboard

এই ওয়েব অ্যাপ্লিকেশনটি **MEP GROUP ERP** (`https://mepgrouperp.com/1027/`) থেকে স্বয়ংক্রিয়ভাবে **Daily Floor Requisition** ডেটা এবং প্রতিটি Requisition-এর ভিতরের লাইন আইটেম ডেটা (বিশেষ করে **Req. Qty** এবং **App. Qty / Apply Quantity**) সংগ্রহ করে আধুনিক ড্যাশবোর্ডে প্রদর্শন করে।

---

## প্রধান ফিচারসমূহ

1. **অটোমেটেড স্ক্র্যাপার বট (Background Sync Bot)**:
   - MEP ERP-তে ক্রেডেনশিয়াল (`mep`, `15387`, `anikanik556`) দিয়ে লগইন করে।
   - **Production Module** -> **Daily Floor Requisition** -> **STR Status** (`mr_status.php`) পেজ থেকে Requisition লিস্ট আনে।
   - প্রতিটি Requisition-এর বিস্তারিত ভিউ (`mr_print_view.php`) থেকে আইটেম কোড, নাম, Req. Qty এবং **Apply Quantity (App. Qty)** সংগ্রহ করে।
   - লাইভ প্রগ্রেস বার সহ ব্যাকগ্রাউন্ড সিঙ্ক সাপোর্ট।

2. **ক্যাটাগরি ড্রপডাউন ফিল্টার (Category Dropdowns)**:
   - **Entry By** ড্রপডাউন: নির্দিষ্ট এন্ট্রি পার্সন (উদাঃ Bikash Chand Ray, Ballal Hossen, Md. Sayful Islam, ইত্যাদি) ফিল্টার।
   - **Type** ড্রপডাউন: রিকুইজিশন টাইপ (উদাঃ Spare Parts, Product Consumable, DSTR, ইত্যাদি) ফিল্টার।
   - স্ট্যাটাস ফিল্টার (SPARE UNCHECKED, SPARE CHECKED, RECEIVED, ইত্যাদি)।
   - লাইভ সার্চ ও Date Range ফিল্টার।

3. **দুই ধরণের ভিউ মোড**:
   - **Requisition View (Expandable)**: রিকুইজিশন রো-তে ক্লিক করলে নিচে ড্রপডাউনে ওই রিকুইজিশনের সব লাইন আইটেম এবং **Apply Quantity** দেখা যায়।
   - **All Items & Apply Qty View**: একসাথে সকল আইটেম এবং পাশে **Apply Quantity** সরাসরি টেবিল আকারে দেখার সুবিধা।
   - **Voucher Modal**: MEP FAN LIMITED অফিসিয়াল Store Requisition ফরম্যাটে প্রিন্ট করার সুবিধা।

4. **এক্সপোর্ট সুবিধা**:
   - ফিল্টার করা ডেটা এক ক্লিকে **CSV / Excel** ফাইলে ডাউনলোড করার সুবিধা।

---

## কিভাবে চালাবেন (How to Run)

### পদ্ধতি ১: ডাবল ক্লিকে চালু (Windows)
প্রজেক্ট ফোল্ডারে থাকা `run.bat` ফাইলে ডাবল ক্লিক করুন। এটি স্বয়ংক্রিয়ভাবে সার্ভার চালু করে ব্রাউজারে `http://localhost:8000` ওপেন করবে।

### পদ্ধতি ২: টার্মিনাল কমান্ডের মাধ্যমে
```bash
# প্রজেক্ট ফোল্ডারে টার্মিনাল খুলুন:
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
এরপর ব্রাউজারে প্রবেশ করুন: `http://localhost:8000`

---

## ক্রেডেনশিয়াল কনফিগারেশন (`backend/config.py`)
- URL: `https://mepgrouperp.com/1027/`
- Company ID: `mep`
- Username: `15387`
- Password: `anikanik556`
- Database: `erpcombd`
