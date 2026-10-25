"""Actual lightweight dataset worker from a saved review; never training."""
import json
from playwright.sync_api import expect

def dataset_flow(page,datasets,reviews,characters,screenshots):
    training_requests=[]
    page.on('request',lambda request:training_requests.append(request.url) if '/api/training' in request.url else None)
    page.get_by_role('tab',name='转写',exact=True).click()
    expect(page.get_by_role('heading',name='制作分段数据集',exact=True)).to_be_visible()
    doc=next(item for item in reviews.list()['items'] if item['kind']=='review')
    saved=reviews.get(doc['id']);raw=(reviews.root/(doc['id']+'.json')).read_bytes()
    role=next(role for role in characters.list() if role['name']=='星野 / 测试角色')
    page.get_by_label('数据集角色',exact=True).select_option(role['id'])
    page.get_by_label('数据集名称',exact=True).fill('browser-segments')
    page.get_by_label('第1段文字',exact=True).fill('未保存的修改不能构建')
    expect(page.get_by_role('button',name='生成分段数据集',exact=True)).to_be_disabled()
    page.once('dialog',lambda dialog:dialog.accept());page.get_by_role('button',name='重新加载转写',exact=True).click()
    expect(page.get_by_role('button',name='生成分段数据集',exact=True)).to_be_enabled()
    page.get_by_role('button',name='生成分段数据集',exact=True).click()
    expect(page.locator('#dataset-build-status')).to_contain_text('已生成 2 个片段',timeout=15000)
    manifest=datasets.get('browser-segments');assert manifest['entry_count']==2 and manifest['total_duration']==2
    assert (reviews.root/(doc['id']+'.json')).read_bytes()==raw
    expect(page.locator('[data-dataset-name="browser-segments"]')).to_contain_text('2 个片段')
    before=(datasets.root/'browser-segments'/'dataset.json').read_bytes()
    page.get_by_role('button',name='生成分段数据集',exact=True).click()
    expect(page.locator('#dataset-build-status')).to_contain_text('构建失败')
    assert (datasets.root/'browser-segments'/'dataset.json').read_bytes()==before
    page.get_by_label('数据集名称',exact=True).fill('CON');page.get_by_role('button',name='生成分段数据集',exact=True).click()
    expect(page.locator('#dataset-build-status')).to_contain_text('构建失败')
    assert not (datasets.root/'CON').exists()
    for status in (429,503,504):
        route_pattern='**/api/datasets/segments'
        page.route(route_pattern,lambda route,request,status=status:route.fulfill(status=status,json={'detail':'模拟构建错误'+str(status)}))
        page.get_by_label('数据集名称',exact=True).fill('error'+str(status))
        page.get_by_role('button',name='生成分段数据集',exact=True).click()
        expect(page.locator('#dataset-build-status')).to_contain_text('模拟构建错误'+str(status))
        page.unroute(route_pattern)
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value(saved['transcript']['segments'][0]['text'])
    page.get_by_label('数据集名称',exact=True).fill('browser-segments-copy');page.get_by_role('button',name='生成分段数据集',exact=True).click()
    expect(page.locator('#dataset-build-status')).to_contain_text('已生成 2 个片段',timeout=15000)
    page.locator('#dataset-builder').scroll_into_view_if_needed();page.screenshot(path=str(screenshots/'studio-datasets-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':900});page.screenshot(path=str(screenshots/'studio-datasets-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
    page.set_viewport_size({'width':1440,'height':1050});page.get_by_role('tab',name='音频',exact=True).click()
    assert not training_requests,'Dataset UI must not submit any training requests'
