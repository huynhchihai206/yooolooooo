# Trợ lý câu hỏi Windows — GPT-5.6 Sol / Medium

Bản dùng vùng chụp cố định và phím F8: **chỉ gửi câu hỏi khi người dùng ra lệnh**, không tự tra khi màn hình thay đổi.

## Chức năng

- **F8:** chụp ngay vùng câu hỏi đã chọn rồi gửi tra. Nếu chưa chọn vùng, lấy chữ đang bôi đen hoặc ảnh trong clipboard.
- **F9:** ẩn/hiện ô đáp án.
- Nhiều lần bấm F8 tạo hàng chờ, xử lý lần lượt. `(N) chờ` chỉ đếm các câu chưa bắt đầu xử lý.
- Các đáp án trong cùng đợt được giữ lại và đánh số. Khi không còn câu đang xử lý/chờ, yêu cầu mới bắt đầu đợt mới.
- Ô đáp án nhỏ, nền trong suốt, Arial cỡ 8; kéo chuột để di chuyển, chuột phải để mở menu.
- Nạp tài liệu PDF có chữ, DOCX, TXT hoặc Markdown để làm ngữ cảnh.
- Có thể cập nhật ảnh vùng đã chọn mỗi 0,5 giây trên máy; việc này **không tự gửi tra**. F8 luôn chụp ảnh mới.

## Cách kết nối

Model cố định: **`gpt-5.6-sol`**, mức suy luận **`medium`** trong hàm `command()` của `tro_ly_plus.py`.

Tool gọi **Codex CLI đăng nhập bằng ChatGPT**, không thao tác cửa sổ ChatGPT/Gemini và không dùng khóa OpenAI API trong luồng chạy chính. Cần tài khoản có quyền sử dụng model và còn hạn mức. Không cần mở cửa sổ ChatGPT; cần Internet khi tra.

## Cài đặt

1. Cài Python trên Windows (bản này được kiểm tra với Python 3.14).
2. Cài Codex CLI hoặc ứng dụng Codex có kèm CLI. Xem [hướng dẫn Codex CLI](https://developers.openai.com/codex/cli/). Đảm bảo lệnh `codex` dùng được trong CMD, rồi đăng nhập:

```cmd
codex login
codex login status
```

Chọn đăng nhập bằng tài khoản ChatGPT.

3. Tải repo, giải nén, mở CMD tại thư mục chứa code rồi cài thư viện:

```cmd
py -m pip install -r requirements.txt
```

## Chạy

```cmd
py chay_tool_moi.py
```

Chỉ chạy file này. Giữ các file Python còn lại cùng thư mục và không mở nhiều bản tool đồng thời vì sẽ tranh phím F8/F9. Có thể thu nhỏ cửa sổ CMD nhưng không đóng nó khi tool đang chạy.

## Chọn vùng và tra

1. Chuột phải vào ô chữ → **Khoanh / chọn lại vùng câu hỏi**.
2. Kéo khoanh toàn bộ câu hỏi và các lựa chọn. Nhấn Esc để hủy khoanh.
3. Đặt ô đáp án ngoài vùng chụp.
4. Khi câu hỏi hiện đầy đủ, bấm rồi nhả **F8** một lần.
5. Có thể chuyển sang câu khác và tiếp tục bấm F8; mỗi lần giữ một ảnh riêng trong hàng chờ.

Vùng chọn được lưu vào `vung_theo_doi.json` trên máy, không đưa lên Git. Sau khi đổi màn hình hoặc bố cục trang, hãy khoanh lại vùng.

Menu **Đọc vùng liên tục (không tự tra)** / **Tạm dừng đọc vùng** chỉ bật/tắt việc cập nhật ảnh trên máy. F8 vẫn chụp vùng đã chọn khi việc cập nhật đang tạm dừng.

Muốn lấy chữ bôi đen hoặc ảnh clipboard khi đã chọn vùng, dùng menu **Tra chữ bôi đen / ảnh clipboard**. Có thể chụp ảnh vào clipboard bằng Win+Shift+S.

## Tài liệu và dữ liệu

Chọn **Chọn tài liệu** trong menu chuột phải. Mỗi file tối đa 15 MB, tổng nội dung tối đa 80.000 ký tự. PDF scan cần OCR trước. Ảnh/câu hỏi và nội dung tài liệu đã nạp được gửi tới dịch vụ trả lời khi tra; ảnh chụp tạm được dọn sau lượt xử lý.

Repo không chứa thông tin đăng nhập, khóa API, ảnh câu hỏi, tài liệu cá nhân hoặc vùng màn hình đã lưu.

## Các file cần giữ

| File | Vai trò |
|---|---|
| `chay_tool_moi.py` | Điểm chạy chính, F8/F9 và hàng chờ |
| `theo_doi_vung.py` | Khoanh vùng, cập nhật ảnh và menu |
| `chay_tool.py` | Đăng ký phím tắt Windows |
| `tro_ly_plus.py` | Gọi Codex, chọn model và vẽ ô đáp án |
| `tro_ly_cau_hoi.py` | File cũ cung cấp hàm đọc tài liệu |

`tro_ly_cau_hoi.py` được giữ nguyên vì bản chính đang nhập hàm đọc tài liệu từ file này. Nó có luồng API cũ riêng; **không chạy trực tiếp file này**. Thư viện `openai` vẫn cần vì file này có import SDK.

## Khắc phục nhanh

- **Phím tắt đã bị chiếm:** thoát bản tool cũ bằng menu **Thoát**, rồi mở lại.
- **Không tìm thấy Codex:** kiểm tra cài đặt và PATH bằng `where codex`.
- **Chưa đăng nhập:** chạy `codex login`, chọn ChatGPT.
- **Model không được hỗ trợ/hết hạn mức:** kiểm tra quyền truy cập tài khoản, phiên bản Codex và hạn mức. Tool không tự đổi model.
- **Ảnh thiếu câu hỏi:** khoanh lại để bao trọn nội dung, giữ ô đáp án ngoài vùng chụp.

Sau khi sửa code hoặc model, thoát và mở lại tool để áp dụng.

## Kiểm tra bản đóng gói

Đã kiểm tra cú pháp, cấu hình model, hàng chờ/giữ đáp án và việc cập nhật vùng không tự gửi bằng mô phỏng. Chưa xác nhận một lượt gọi GPT-5.6 Sol trực tiếp trong bước đóng gói repo này.
