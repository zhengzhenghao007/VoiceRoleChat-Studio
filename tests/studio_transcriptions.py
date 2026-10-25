"""Additional isolated transcript UI acceptance, called by studio_browser."""
import json,re,threading
from unittest.mock import patch
from playwright.sync_api import expect
from schemas.transcript_review import ReviewUpdate

def transcription_flow(page,jobs,reviews,root,screenshots):
    page.get_by_role('button',name='library-source.wav',exact=True).click()
    page.get_by_role('button',name='转写此音频',exact=True).click()
    expect(page.get_by_role('heading',name='转写与校对',exact=True)).to_be_visible()
    expect(page.get_by_label('转写音频',exact=True)).not_to_have_value('')
    page.get_by_label('识别语言',exact=True).select_option('ja')
    page.get_by_role('button',name='提交后台转写',exact=True).click()
    expect(page.locator('#notice')).to_contain_text('已提交后台转写')
    queued=next(item for item in jobs.list()['items'] if item['state']=='queued')
    card=page.locator('[data-job-id="'+queued['id']+'"]');expect(card).to_contain_text('排队中')
    jobs._tick();expect(card).to_contain_text('运行中')
    card.get_by_role('button',name='取消转写',exact=True).click();expect(card).to_contain_text('取消中')
    jobs._tick();expect(card).to_contain_text('已取消')
    page.get_by_role('button',name='提交后台转写',exact=True).click()
    expect(page.locator('#notice')).to_contain_text('已提交后台转写')
    queued=next(item for item in jobs.list()['items'] if item['state']=='queued');jobs._tick();jobs._tick()
    card=page.locator('[data-job-id="'+queued['id']+'"]');expect(card).to_contain_text('已完成')
    card.get_by_role('button',name='打开识别结果',exact=True).click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('hello')
    raw_id=queued['id'];raw_bytes=(jobs.root/(raw_id+'.json')).read_bytes()
    malicious='<img src=x onerror="window.__transcriptXss=true">校对'
    page.get_by_label('第1段文字',exact=True).fill(malicious)
    page.get_by_role('button',name='保存校对副本',exact=True).click()
    expect(page.locator('#notice')).to_contain_text('校对已保存')
    review=next(item for item in reviews.list()['items'] if item['kind']=='review');identity=review['id']
    assert (jobs.root/(raw_id+'.json')).read_bytes()==raw_bytes
    assert page.evaluate('window.__transcriptXss !== true')
    current=reviews.get(identity)
    reviews.update(identity,ReviewUpdate(expected_revision=current['revision'],expected_sha256=current['sha256'],language='ja',segments=[dict(start=0,end=3,text='另一客户端的修订')]))
    page.get_by_label('第1段文字',exact=True).fill('冲突中的草稿')
    page.get_by_role('button',name='保存校对修改',exact=True).click()
    expect(page.locator('#notice')).to_contain_text('保存冲突')
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('冲突中的草稿')
    page.once('dialog',lambda dialog:dialog.dismiss());page.get_by_role('button',name='重新加载转写',exact=True).click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('冲突中的草稿')
    page.once('dialog',lambda dialog:dialog.accept());page.get_by_role('button',name='重新加载转写',exact=True).click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('另一客户端的修订')
    page.get_by_label('第1段文字',exact=True).fill('已提交的版本')
    update=reviews.update;entered,release=threading.Event(),threading.Event()
    def delayed_update(*args):
        entered.set();release.wait(5);return update(*args)
    with patch.object(reviews,'update',side_effect=delayed_update):
        with page.expect_response(lambda response:response.request.method=='PATCH' and response.url.endswith('/reviews/'+identity)) as pending:
            try:
                page.get_by_role('button',name='保存校对修改',exact=True).click();assert entered.wait(1)
                page.get_by_label('第1段文字',exact=True).fill('保存期间的新编辑')
            finally:release.set()
        pending.value.body()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('保存期间的新编辑')
    expect(page.locator('#transcript-draft')).to_have_text('有未保存修改')
    assert reviews.get(identity)['transcript']['text']=='已提交的版本'
    page.once('dialog',lambda dialog:dialog.dismiss())
    page.locator('[data-record-id="'+raw_id+'"]').click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('保存期间的新编辑')
    page.get_by_role('tab',name='音频',exact=True).click();page.get_by_role('tab',name='转写',exact=True).click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('保存期间的新编辑')
    page.get_by_label('第1段结束秒',exact=True).fill('1')
    page.get_by_role('button',name='添加片段',exact=True).click();page.get_by_label('第2段文字',exact=True).fill('第二段')
    page.get_by_role('button',name='添加片段',exact=True).click();page.get_by_label('第3段文字',exact=True).fill('第三段')
    page.get_by_role('button',name='上移第3段',exact=True).click()
    expect(page.locator('#review-validation')).to_contain_text('顺序')
    expect(page.get_by_role('button',name='保存校对修改',exact=True)).to_be_disabled()
    page.get_by_role('button',name='下移第2段',exact=True).click();page.get_by_role('button',name='删除第3段',exact=True).click()
    page.get_by_role('button',name='保存校对修改',exact=True).click();expect(page.locator('#notice')).to_contain_text('校对已保存')
    assert len(reviews.get(identity)['transcript']['segments'])==2
    get=reviews.get;entered,release=threading.Event(),threading.Event()
    def delayed_get(identifier):
        if identifier==raw_id:entered.set();release.wait(5)
        return get(identifier)
    with patch.object(reviews,'get',side_effect=delayed_get):
        with page.expect_response(lambda response:response.url.endswith('/records/'+raw_id)) as pending:
            try:
                page.locator('[data-record-id="'+raw_id+'"]').evaluate('el=>el.click()');assert entered.wait(1)
                page.locator('[data-record-id="'+identity+'"]').evaluate('el=>el.click()')
            finally:release.set()
        pending.value.body()
    expect(page.locator('#transcript-kind')).to_have_text('校对副本')
    route_pattern='**/api/transcriptions/records/'+raw_id
    page.route(route_pattern,lambda route:route.abort())
    page.locator('[data-record-id="'+raw_id+'"]').click()
    expect(page.locator('#notice')).to_contain_text('转写读取失败')
    expect(page.locator('[data-record-id="'+identity+'"]')).to_have_class(re.compile(r'active'))
    page.unroute(route_pattern)
    page.locator('[data-record-id="'+raw_id+'"]').click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('hello')
    expect(page.locator('#notice')).not_to_contain_text('转写读取失败')
    page.locator('[data-record-id="'+identity+'"]').click()
    expect(page.get_by_label('第1段文字',exact=True)).to_have_value('保存期间的新编辑')
    doc=reviews.get(identity);audio=root/'uploads'/doc['transcript']['stored_filename'];hidden=root/'hidden-source.wav'
    audio.rename(hidden)
    try:
        page.get_by_role('button',name='重新加载转写',exact=True).click()
        expect(page.locator('#transcript-audio-missing')).to_be_visible()
        expect(page.get_by_label('第1段文字',exact=True)).to_have_value('保存期间的新编辑')
        page.screenshot(path=str(screenshots/'studio-transcript-desktop.png'),full_page=True)
    finally:hidden.rename(audio)
    page.get_by_role('button',name='重新加载转写',exact=True).click();expect(page.locator('#transcript-audio')).to_be_visible()
    page.set_viewport_size({'width':390,'height':900});page.screenshot(path=str(screenshots/'studio-transcript-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
    page.set_viewport_size({'width':1440,'height':1050})
    requests=[]
    page.on('request',lambda request:requests.append(request.url) if request.url.endswith('/api/transcriptions/jobs') and request.method=='GET' else None)
    page.get_by_role('tab',name='音频',exact=True).click();page.wait_for_load_state('networkidle');count=len(requests)
    page.wait_for_timeout(1500);assert len(requests)==count,'Hidden transcription tab kept polling jobs'
    page.get_by_role('tab',name='转写',exact=True).click();page.wait_for_timeout(1500);assert len(requests)>count
    page.get_by_role('tab',name='音频',exact=True).click()
