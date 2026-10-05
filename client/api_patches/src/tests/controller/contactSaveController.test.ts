import {
  removeContact,
  saveContact,
  toWid,
} from '../../controller/contactSaveController';

function mockRes() {
  const res: any = { statusCode: 0, body: null };
  res.status = (code: number) => {
    res.statusCode = code;
    return res;
  };
  res.json = (payload: any) => {
    res.body = payload;
    return res;
  };
  return res;
}

/** A page whose evaluate() answers what the in-page function would. */
function mockPage(answer: any, closed = false) {
  const calls: any[] = [];
  return {
    calls,
    isClosed: () => closed,
    evaluate: async (_fn: unknown, arg: unknown) => {
      calls.push(arg);
      if (answer instanceof Error) throw answer;
      return answer;
    },
  };
}

function mockReq(body: any, page?: any) {
  return { body, client: page ? { page } : undefined } as any;
}

describe('toWid', () => {
  it('takes the id statusConnection resolved (an array)', () => {
    expect(toWid(['553199999999@c.us'])).toBe('553199999999@c.us');
  });

  it('turns bare digits into a phone id', () => {
    expect(toWid('+55 (31) 99999-9999')).toBe('5531999999999@c.us');
  });

  it('keeps a whole @lid', () => {
    expect(toWid('123456789012345@lid')).toBe('123456789012345@lid');
  });

  it.each([
    '120363067944453158@g.us',
    'status@broadcast',
    '5531999999999@s.whatsapp.net',
    '5531999999999@c.us; drop',
    'abc@c.us',
    '123@c.us',
    '',
    undefined,
    [],
  ])('refuses %p', (value) => {
    expect(toWid(value)).toBe('');
  });
});

describe('saveContact', () => {
  it('sends only its own fields to the page and answers the resolved id', async () => {
    const page = mockPage({ isMyContact: true, syncToAddressbook: true });
    const res = mockRes();
    await saveContact(
      mockReq(
        {
          phone: ['553199999999@c.us'],
          name: '  Ana ',
          lastName: 'Silva',
          anything: 'else',
        },
        page
      ),
      res
    );
    expect(page.calls).toEqual([
      {
        id: '553199999999@c.us',
        name: 'Ana',
        lastName: 'Silva',
        syncAddressBook: true,
      },
    ]);
    expect(res.statusCode).toBe(200);
    expect(res.body.response).toEqual({
      id: '553199999999@c.us',
      isMyContact: true,
      syncToAddressbook: true,
    });
  });

  it('refuses an id that is not a contact before touching the page', async () => {
    const page = mockPage({});
    const res = mockRes();
    await saveContact(mockReq({ phone: 'x@g.us', name: 'Ana' }, page), res);
    expect(page.calls).toEqual([]);
    expect(res.statusCode).toBe(400);
    expect(res.body).toEqual({ status: 'error', code: 'contact_invalid' });
  });

  it('refuses an empty name', async () => {
    const res = mockRes();
    await saveContact(
      mockReq({ phone: '5531999999999', name: '  ' }, mockPage({})),
      res
    );
    expect(res.body.code).toBe('contact_name_required');
  });

  it('answers 503 when there is no live page', async () => {
    const res = mockRes();
    await saveContact(mockReq({ phone: '5531999999999', name: 'Ana' }), res);
    expect(res.statusCode).toBe(503);
    expect(res.body.code).toBe('contact_not_available');
  });

  it('never returns the text of an exception', async () => {
    const res = mockRes();
    await saveContact(
      mockReq(
        { phone: '5531999999999', name: 'Ana' },
        mockPage(new Error('Ana Silva 5531999999999 exploded'))
      ),
      res
    );
    expect(res.statusCode).toBe(502);
    expect(res.body).toEqual({
      status: 'error',
      code: 'contact_operation_failed',
    });
  });

  it('maps an unknown in-page code to the generic one', async () => {
    const res = mockRes();
    await saveContact(
      mockReq(
        { phone: '5531999999999', name: 'Ana' },
        mockPage({ code: 'Ana Silva is not valid' })
      ),
      res
    );
    expect(res.body.code).toBe('contact_operation_failed');
  });
});

describe('removeContact', () => {
  it('removes by the id the client sent', async () => {
    const page = mockPage({});
    const res = mockRes();
    await removeContact(mockReq({ phone: '123456789012345@lid' }, page), res);
    expect(page.calls).toEqual(['123456789012345@lid']);
    expect(res.statusCode).toBe(200);
  });

  it('passes on that the number is not a contact', async () => {
    const res = mockRes();
    await removeContact(
      mockReq(
        { phone: '5531999999999' },
        mockPage({ code: 'number_is_not_your_contact' })
      ),
      res
    );
    expect(res.statusCode).toBe(400);
    expect(res.body.code).toBe('number_is_not_your_contact');
  });
});
