# FileManager 檔案管理系統

統一的 Windows 檔案工作台（PyQt6），整合檔案瀏覽、搜尋、比對／同步、雜湊、
壓縮檔、批量複製／搬移／刪除、重複檔案清理與批次改名，並以統一任務中心管理
所有長時間操作。

介面預設為英文；可在「設定 → 語言」切換為繁體中文，重新啟動後生效。
切換語言不會修改檔案名稱、路徑或 Windows 產生的系統訊息；Qt 內建按鈕、
檔案選擇器與右鍵選單會載入對應語言，TXT／CSV／XLSX 匯出內容也會跟隨目前介面語言。

## 功能模組

| 模組 | 說明 |
| --- | --- |
| 儀表板 | 磁碟與資料夾分析、volume label／UNC 網路磁碟、任務中心、清理建議、最近操作、我的最愛、快速整理 |
| 檔案瀏覽器 | 雙窗格、UNC 網路共享、分頁記憶、縮圖／清單、預覽、我的最愛群組、拖放、複製／搬移／改名／資源回收筒刪除 |
| 檔案搜尋 | 多根目錄、萬用字元／正規表示式、大小／日期／類型／排除樣式、串流結果與批量操作；使用 `os.scandir` 降低重複檔案查詢 |
| 批量複製 / 搬移 | 單一頁面切換複製或搬移；依 CSV、副檔名或自訂萬用字元挑選；平行傳輸、保留結構、衝突策略、快速／完整驗證、暫停／取消、網路重試、長路徑；搬移在同磁碟區使用原子 rename |
| 批量刪除 | 依副檔名、日期、大小、排除樣式掃描；預設資源回收筒；TXT／CSV／XLSX 稽核 |
| 重複檔案 | 最小大小、排除樣式、硬連結忽略、SHA-256 偵測、預覽與保留策略 |
| 批次改名 | 尋找取代／前後綴／編號／大小寫；背景預覽與套用 |
| 資料夾比對 | 僅左／僅右／較新／內容不同／類型衝突；同步預覽、鏡像刪除與 CSV |
| 雜湊工具 | MD5／SHA-1／SHA-256、批次資料夾、兩檔比對、CSV |
| 壓縮檔 | ZIP／TAR 瀏覽、解壓、建立 ZIP；路徑穿越與 zip bomb 防護 |
| 設定 | 主題、啟動頁、衝突策略、驗證、執行緒、瀏覽器與歷史設定 |

## 網路磁碟

- 儀表板磁碟卡顯示磁碟區標籤（volume label）、檔案系統、磁碟類型與 UNC 目標。
- 可直接輸入 `\\10.8.17.66` 瀏覽伺服器共享，或輸入 `\\server\share` 開啟資料夾。
- 儀表板可新增／移除並記住 UNC 網路位置。
- 需要帳號密碼時可在「網路共享」視窗輸入；密碼只用於本次連線，不會寫入設定檔。
- 所有顯示路徑統一使用 Windows 的 `\` 分隔符，UNC 開頭 `\\` 不會被破壞。

## 效能與長路徑

- 瀏覽器與批量複製／搬移共用傳輸引擎：多執行緒、Windows `CopyFileExW` 快速路徑、Python 後備複製。
- 可選快速驗證（大小＋首尾內容）、完整驗證（SHA-256）或關閉驗證；網路錯誤可設定自動重試次數。
- 複製與搬移支援 `\\?\` 長路徑，並保留檔案時間與屬性。
- 搜尋、Dashboard 掃描、重複檔案與刪除掃描使用 `os.scandir`／長路徑安全路徑。
- 瀏覽器縮圖只在啟用縮圖檢視時解碼，清單模式使用輕量系統圖示。

## 介面設計

- 單色線性 SVG icon，不使用 emoji 作為結構性圖示
- 深／淺主題共用語義色 token，文字對比 ≥ 4.5:1
- 側邊欄以工作區／批量處理／工具分組；頂部有醒目的「Collapse sidebar」按鈕，也可按 `Ctrl+B` 折疊
- 每頁一致的 Page Header、空狀態與操作層級
- 任務中心顯示狀態 badge、進度與篩選
- 鍵盤 focus ring、工具提示與 accessible name
- 英文為預設語言，繁體中文可於設定切換；應用程式圖示使用多尺寸 `assets/app_icon.ico`

## 需求

- Windows 10/11
- Python 3.10+
- 依賴：PyQt6、Send2Trash、openpyxl（見 `requirements.txt`）

## 開發

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

python main.py            # 啟動
python -m pytest          # 測試
python -m ruff check app  # 靜態檢查
```

## 快捷鍵

- `Ctrl+K`：命令面板
- `Ctrl+Shift+J`：任務中心
- `Ctrl+B`：收起／展開側邊欄
- `Ctrl+1`～`Ctrl+9`：切換前九個頁面
- 檔案瀏覽器：`F5` 重新整理、`F2` 重新命名、`Del` 移至資源回收筒、`F3` 預覽
- 檔案瀏覽器：`Ctrl+C`／`Ctrl+X`／`Ctrl+V` 複製、剪下、貼上
- 檔案瀏覽器：`Ctrl+Shift+N` 新增資料夾、`Ctrl+Shift+T` 恢復最近關閉分頁
- 檔案瀏覽器：`Alt+←`／`Alt+→`／`Alt+↑` 上一頁／下一頁／上一層

## 打包

```powershell
.\venv\Scripts\python.exe -m PyInstaller FileManager.spec --noconfirm
```

採 onedir 模式（`dist/FileManager/`），避免 onefile 自我解壓觸發防毒誤判。
打包時會一併包含 `assets/app_icon.ico` 與 `assets/i18n/`，因此 EXE、標題列與
工作列圖示，以及英文介面在打包後仍可正常載入。
版本號以 `app/core/constants.py` 的 `APP_VERSION_TUPLE` 為單一來源，並由
`tests/test_packaging.py` 驗證與 `version_info.txt` 一致。

## 專案結構

```
main.py                     進入點
app/
  core/                     共用邏輯（無 UI 依賴）
    constants.py            常數、版本、模組與導覽分組
    models.py               資料模型
    settings.py             QSettings 封裝與設定遷移
    i18n.py                 英文顯示字串目錄與執行期 localizer
    favorites.py            我的最愛與群組
    tasks.py                任務中心資料模型
    history.py              操作歷史 JSON 與統計
    workers.py              取消／暫停控制、原子複製、BaseWorker
    file_ops.py             共用回收筒與路徑工具
    transfer.py             共用複製／搬移引擎、驗證、重試與長路徑
    drives.py               磁碟標籤、UNC 共享列舉與網路連線
    compare.py              資料夾比對與同步計畫
    hashing.py              串流雜湊
    archive.py              ZIP／TAR 安全處理
    search.py               串流搜尋
    utils.py                路徑正規化、格式化、分類、排除比對、資源回收筒、雜湊
    theme.py                亮／暗主題 QSS
  ui/                       應用外殼與共用元件
    main_window.py          分組側邊欄、任務中心、命令面板、快捷鍵
    icons.py                主題化線性 SVG icon
    components.py           PageHeader、EmptyState、StatusBadge
    widgets.py              路徑欄、拖放區、副檔名 chips
    path_utils.py           Qt／UNC 路徑檢查
    network_dialog.py       網路共享選擇與 UNC 連線對話框
    charts.py               KPI 卡、環形圖、比例長條
    task_center.py          統一任務中心
    command_palette.py      Ctrl+K 命令面板
    history_dialog.py       可篩選／匯出的歷史紀錄對話框
    base.py                 ModulePage 基底（payload／主題／任務 hook）
  modules/                  各功能模組（page + 純邏輯 + worker）
    dashboard/              掃描器、快取、清理建議
    browser/                雙窗格、縮圖、預覽、檔案操作、我的最愛群組
    search/ compare/ hash/ archive/ settings/
    copier/ remover/ duplicates/ renamer/
assets/
  app_icon.ico              多尺寸應用程式圖示
  i18n/en.json              英文介面字串目錄
tests/                      pytest（Qt 以 offscreen 執行）
```

## 測試

測試以 `QT_QPA_PLATFORM=offscreen` 執行，不需螢幕：

```text
所有測試通過（掃描器、快取、瀏覽器操作、歷史與 UI smoke）
```
