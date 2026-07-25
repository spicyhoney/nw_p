# Reference Data

`taiwan_admin_areas.json` 是由
[內政部國土測繪中心行政區 API](https://data.gov.tw/dataset/102011)
取得的固定版本快照，採政府資料開放授權條款第 1 版。

快照保存來源網址、擷取時間與原始／正規化名稱。需要更新時執行：

```powershell
python .\scripts\fetch_admin_reference.py
```

更新後必須重新執行清洗與測試，並檢查行政區筆數或代碼是否有變動。
