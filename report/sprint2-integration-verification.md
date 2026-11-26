# CN21-13 — Kiểm chứng bản tích hợp 26/11/2026

## Source và phương pháp đồng bộ

Nhánh thực hiện: **ha-nguyet**. Đồng bộ main tại **3c5373116525d6eb52c125d808eef7343026dd8a**, sau PR #7 Storage, #9 Server, #8 Client Reliability và #6 runner. Giữ lịch sử hai phía bằng merge; không force-push/rewrite main hoặc nhánh thành viên.

- src/client/client.py giữ nguyên source main: SERVER_BUSY fatal, FILE_BUSY recoverable, no greeting wait, exclusive operation guard, reconnect, safe download, các constructor fields và schema/timeout cho runner.
- src/server/server.py, storage.py, config.py, common/protocol.py và common/transfer.py giữ nguyên source main. Server gọi locked(filename, owner=connection_id), release_all khi dọn worker.
- scripts/run_concurrent.py giữ validate_worker_rows riêng của ha-nguyet: fixture size, UUID/timezone, IDs, num_clients, chunk, metric và lý do FAILED.
- tests/test_concurrent_runner.py áp dụng production Server/Storage mặc định, đối chứng SequentialFileServer riêng và các test bổ sung của ha-nguyet. Không còn thêm trùng max_clients vào config.
- Baseline Sprint 1 giữ nguyên dữ liệu. Mẫu lịch sử 22–23/11 giữ nguyên; mẫu cũ từ main vẫn truy được trong lịch sử main.
- pytest.ini giới hạn testpaths=tests để pytest không thu nhầm test của runtime/dependency được cài trong thư mục scratch.

PR #10 còn OPEN tại thời điểm đồng bộ, không nằm trong source này. Các test/timeout-label fix của PR đó không bị copy vào nhánh ngoài luồng review.

## Full regression độc lập

| Môi trường thực tế | Kết quả project tests |
| --- | --- |
| Linux, Python 3.12.14, pytest 8.4.2 | 141 passed |
| Linux, Python 3.11.17, pytest 8.4.2 | 141 passed |

```bash
PYTHONPATH=src python -m pytest -q
```

Hai lần trên chỉ tính test của project. Lần dò ban đầu của Python 3.11 có thêm test của dependency/runtime trong work; không dùng số đó làm số test dự án. pytest.ini và lần chạy project 141 test loại bỏ sai lệch này.

Suite bao gồm Client Reliability, storage locking, server concurrency/FILE_BUSY production, regression Sprint 1 và các test runner/CSV. Không dùng fixture thread thay production server để khẳng định concurrency thành công; fixture tuần tự chỉ để kiểm tra FAIL gate.

Logs: [python311-pytest.log](../results/sprint2-integration-2026-11-26/python311-pytest.log), [python312-pytest.log](../results/sprint2-integration-2026-11-26/python312-pytest.log).

## Sáu phiên CLI thật

Mỗi phiên: một tiến trình runner, N FileClient/socket, ba file đúng 1.000.000 / 10.000.000 / 50.000.000 byte, upload + download. Server/client cùng Linux qua loopback, chunk 65536 byte, max_clients=10, không chủ động giới hạn băng thông.

| Python | N | Dòng CSV | Kết quả |
| --- | --- | --- | --- |
| 3.11.17 | 1 / 5 / 10 | 6 / 30 / 60 | Tất cả PASS |
| 3.12.14 | 1 / 5 / 10 | 6 / 30 / 60 | Tất cả PASS |

Tất cả 192 transfer SUCCESS/checksum true. Đã kiểm tra thêm byte/hash nguồn, đường dẫn upload, file nhận Server và download của 96 cặp file. Gate READY trước payload và khoảng payload/completion chồng lấn dương. Chi tiết UUID/timestamp/overlap: [run-matrix.json](../results/sprint2-integration-2026-11-26/run-matrix.json).

Mẫu CSV đầy đủ Python 3.11 và metadata: [results/sprint2-integration-2026-11-26](../results/sprint2-integration-2026-11-26). Mẫu công khai lược hardware riêng nhưng không đổi số đo. Source hashes và main reference giúp xác định working tree thực thi trước commit. Server thử nghiệm đã dừng sau từng đợt.

## Giới hạn còn mở

- Đây là Linux/loopback; chưa có bằng chứng Windows/Python 3.11 và LAN PC Server Ethernet → laptop Wi-Fi. Không đánh dấu CN21-14/Sprint 2 ACCEPTED từ các log này.
- PR #10 đang mở: có sửa timeout label theo socket_timeout và test Client/Server thật bổ sung, thuộc owner Client.
- Review PR #9 có P1: worker.start() lỗi do hết tài nguyên thread có thể làm dừng accept loop. Không tái hiện hoặc sửa source Server trong CN21-13; cần owner/Team Lead xử lý hoặc chấp nhận giới hạn.
- Các kiểm tra CSV bổ sung trong ha-nguyet cần được review nếu đưa vào main; PR #6 đã merge bản runner cũ không tự đưa các commit riêng sau đó vào main.

Trạng thái: **bản đồng bộ đã chạy regression và CLI loopback thành công; chờ review cùng Windows/LAN trước nghiệm thu cuối**.
