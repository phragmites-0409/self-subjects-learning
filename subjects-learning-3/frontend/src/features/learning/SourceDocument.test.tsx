import {render,screen,cleanup} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {MathText} from './shared';
afterEach(cleanup);
it('renders source formula and diagram at their anchors without replacing ordinary math',()=>{
  const {container}=render(<MathText text={'前文\n[[图块:1]]\n条件 $x^2$\n[[图块:2]]\n后文'} images={[{key:'1',asset_id:'formula',kind:'formula',label:'反应方程式'},{key:'2',asset_id:'diagram',kind:'diagram',label:'原题甲乙图'}]}/>);
  expect(screen.getByAltText('反应方程式')).toHaveAttribute('src',expect.stringContaining('/formula/download'));
  expect(screen.getByAltText('原题甲乙图')).toBeInTheDocument();
  expect(container.textContent).not.toContain('[[图块:');expect(container.querySelector('.katex')).toBeTruthy();
  expect(container.querySelectorAll('.source-inline')).toHaveLength(2);
});
it('keeps an inline source crop inside a paragraph and typesets chemical notation',()=>{
  const {container}=render(<MathText text={'条件 $\\ce{2H2 + O2 -> 2H2O}$，[[图块:1]] 后文'} images={[{key:'1',asset_id:'fraction',kind:'formula',placement:'inline'}]}/>);
  expect(container.querySelector('.katex-error')).toBeNull();
  expect(container.querySelector('.typeset-math .katex')).toBeTruthy();
  expect(container.querySelector('.source-formula-inline img')).toBeTruthy();
  expect(container.querySelector('figure')).toBeNull();
});
