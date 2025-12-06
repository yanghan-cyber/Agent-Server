from markitdown import MarkItDown
md = MarkItDown(enable_plugins=False) # Set to True to enable plugins

res = md.convert("http://jyt.hunan.gov.cn/jyt/sjyt/hnzxxjsfzzx/jsfzzxtzgg/201912/10783971/files/be971fe3dbf24ab988f0641314c9e91a.pdf")
print(res.text_content)