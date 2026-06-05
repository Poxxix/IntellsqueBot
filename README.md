# Telegram Bot cho nhóm văn phòng (Office Bot)

Đây là Telegram Bot dành cho nhóm nội bộ văn phòng để giảm thao tác thủ công cho các công việc lặp lại hàng ngày như phân công lấy cơm, ghi nhận xin nghỉ phép, nhắc lịch và các tác vụ hành chính nhẹ.

## 🚀 Tính năng nổi bật

1. **Chọn người lấy cơm ngẫu nhiên (`/comhomnay`):**
   - Lọc người đang nghỉ phép hôm nay.
   - Lọc người đã tắt tham gia lấy cơm.
   - Áp dụng luật công bằng (ưu tiên chọn người chưa đi lấy lâu nhất và loại trừ người đi lấy trong $N$ ngày gần đây).
   - Hỗ trợ **Reroll** (chọn lại), **Xác nhận** và **Bỏ qua** thông qua các nút bấm inline.
   - Lưu lịch sử lấy cơm (`/lichsu_com`).

2. **Đăng ký xin nghỉ phép (`/xinnghi`):**
   - Đơn xin nghỉ theo buổi (sáng, chiều), cả ngày hoặc nghỉ nhiều ngày liên tục.
   - Hỗ trợ nút bấm xin nghỉ nhanh hôm nay/ngày mai.
   - **Quy trình phê duyệt thông minh:** Gửi đơn trực tiếp đến các quản lý (Admin/Approver) qua DM kèm nút **Duyệt / Từ chối**.
   - Ẩn lý do nghỉ chi tiết khi thông báo ra nhóm chung nhằm bảo mật thông tin cá nhân.
   - Xem nhanh danh sách người nghỉ hôm nay (`/nghihomnay`) và người đi làm (`/ailamviec`).

3. **Nhắc lịch & Reminder:**
   - Hẹn giờ nhắc việc một lần (`/remind 16:30 Nộp timesheet` hoặc `/remind 15m Đổ rác`).
   - Tạo lịch nhắc định kỳ (`/taolich "Họp standup" 09:00 weekdays`).
   - Nhắc việc lặp lại sau X ngày (`/nhacviec add "Tưới cây" every 3 days 09:00`).
   - Xem danh sách lịch nhắc (`/lichnhac`) kèm nút bấm xóa nhanh.

4. **Trạng thái văn phòng (`/statushomnay`):**
   - Tổng hợp nhanh tình hình trong ngày: ai nghỉ phép, ai đi lấy cơm hôm nay, các nhắc lịch đang hoạt động.

5. **Phân quyền & Tự động đăng ký:**
   - Hỗ trợ các role: `member`, `approver`, `admin`, `hr`.
   - **Tự động đăng ký:** Thành viên chỉ cần tương tác (nhắn tin hoặc nhấn nút) với bot, hệ thống sẽ tự động lưu thông tin.
   - Thành viên đầu tiên bắt đầu chat với bot khi database trống sẽ được cấp quyền **Admin** tự động để tiện quản trị.

---

## 🛠️ Cài đặt & Chạy cục bộ (Local Development)

### 1. Chuẩn bị
- Đã cài đặt [Node.js](https://nodejs.org/) (phiên bản 18+ được khuyến nghị) và `npm`.
- Đã tạo bot và lấy Token từ [@BotFather](https://t.me/BotFather).

### 2. Cài đặt các thư viện
Di chuyển vào thư mục dự án và chạy:
```bash
npm install
```

### 3. Cấu hình biến môi trường
Mở file `.env` và cập nhật thông tin:
- `BOT_TOKEN`: Token của Telegram Bot nhận từ BotFather.
- `DATABASE_PATH`: Đường dẫn lưu file cơ sở dữ liệu SQLite (mặc định `./data/office_bot.db`).
- `DEFAULT_ADMIN_IDS`: Telegram ID của các admin phụ trợ (phân tách bằng dấu phẩy).
- `TZ`: Múi giờ (`Asia/Ho_Chi_Minh` cho múi giờ Việt Nam).

### 4. Chạy dự án
- Chạy ở chế độ phát triển (sử dụng `ts-node` tự động tải lại):
  ```bash
  npm run dev
  ```
- Biên dịch sang JavaScript và chạy ở chế độ production:
  ```bash
  npm run build
  ```
  ```bash
  npm run start
  ```

---

## ⚙️ Hướng dẫn sử dụng & Danh sách lệnh

| Lệnh | Vai trò | Mô tả |
| :--- | :--- | :--- |
| `/start` | Tất cả | Khởi động bot và xem tin nhắn chào mừng |
| `/help` | Tất cả | Xem tài liệu hướng dẫn sử dụng chi tiết |
| `/comhomnay` | Tất cả | Chọn ngẫu nhiên 1 người đi lấy cơm hôm nay |
| `/rerollcom` | Tất cả | Chọn lại người đi lấy cơm |
| `/thamgia_com on\|off` | Tất cả | Bật/tắt tham gia danh sách random cơm trưa |
| `/lichsu_com` | Tất cả | Xem lịch sử chọn người lấy cơm 7 lần gần nhất |
| `/xinnghi` | Tất cả | Hướng dẫn xin nghỉ phép & hiển thị nút nghỉ nhanh |
| `/nghihomnay` | Tất cả | Xem danh sách những người được duyệt nghỉ hôm nay |
| `/ailamviec` | Tất cả | Xem danh sách những người đi làm hôm nay |
| `/statushomnay` | Tất cả | Xem trạng thái văn phòng tổng hợp hôm nay |
| `/remind [thời gian] [nội dung]` | Tất cả | Đặt lịch nhắc nhở một lần (giờ cố định hoặc đếm ngược) |
| `/taolich "[Tên]" [HH:MM] daily\|weekdays` | Admin/Approver | Tạo lịch nhắc việc định kỳ cho nhóm |
| `/nhacviec add "[Tên]" [X]d [HH:MM]` | Admin/Approver | Nhắc việc định kỳ mỗi X ngày |
| `/lichnhac` | Tất cả | Xem danh sách và xóa các lịch nhắc đang hoạt động |
| `/admin` | Admin | Quản lý thành viên và quyền hạn |
| `/setrole [@username/ID] [role]` | Admin | Phân quyền cho thành viên (`member`, `approver`, `admin`, `hr`) |

---

## 🏗️ Kiến trúc mã nguồn
Mã nguồn được thiết kế phân chia module rõ ràng:
- `src/config.ts`: Đọc cấu hình và quản lý biến môi trường.
- `src/database/`: Quản lý kết nối SQLite và tạo các bảng dữ liệu tự động.
- `src/models/`: Thực hiện các câu lệnh SQL đóng gói nghiệp vụ (Users, Leaves, Assignments, Reminders, AuditLogs).
- `src/services/`: Chứa scheduler chạy ngầm bằng `node-cron`.
- `src/handlers/`: Tiếp nhận và xử lý tin nhắn, lệnh và callback từ Telegram.
- `src/index.ts`: Điểm khởi chạy của ứng dụng.
