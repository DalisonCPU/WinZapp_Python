/**
 * WinZapp: save / remove a contact that WhatsApp syncs to the phone's address
 * book. WA-JS already has WPP.contact.save / WPP.contact.remove (the same
 * action WhatsApp Web's own "add contact" runs); neither wppconnect nor the
 * server exposes them, so this only forwards to the page.
 */
import type { Request, Response } from 'express';

type SaveCommand = {
  id: string;
  name: string;
  lastName: string;
  syncAddressBook: boolean;
};

const KNOWN_CODES = [
  'contact_not_available',
  'contact_invalid',
  'contact_name_required',
  'contact_not_found',
  'number_is_not_your_contact',
];

function toWid(phone: unknown): string {
  const raw = String(phone ?? '').trim();
  if (raw.includes('@')) return raw.replace(/@c\.us$/, '@c.us');
  const digits = raw.replace(/\D/g, '');
  return digits.length >= 7 ? `${digits}@c.us` : '';
}

function fail(res: Response, error: any) {
  // No arbitrary exception text: native errors can contain names and numbers.
  const code = String(error?.code || '');
  const safe = KNOWN_CODES.includes(code) ? code : 'contact_operation_failed';
  const status = safe === 'contact_not_available' ? 503
    : safe === 'contact_operation_failed' ? 502 : 400;
  return res.status(status).json({ status: 'error', code: safe });
}

function livePage(req: Request, res: Response) {
  const page = (req.client as any)?.page;
  if (!page || page.isClosed()) {
    fail(res, { code: 'contact_not_available' });
    return null;
  }
  return page;
}

export async function saveContact(req: Request, res: Response) {
  // Only our fields enter the page. No function name or arbitrary JS payload.
  const { phone, name, lastName, syncAddressBook } = req.body || {};
  const id = toWid(phone);
  const first = String(name ?? '').trim().slice(0, 100);
  if (!id) return fail(res, { code: 'contact_invalid' });
  if (!first) return fail(res, { code: 'contact_name_required' });
  const page = livePage(req, res);
  if (!page) return;
  const command: SaveCommand = {
    id,
    name: first,
    lastName: String(lastName ?? '').trim().slice(0, 100),
    // Synced to the phone unless the caller says otherwise.
    syncAddressBook: syncAddressBook !== false,
  };
  try {
    // Errors cross page.evaluate as a message only, so the page answers with
    // the WPPError code instead of throwing it.
    const result = await page.evaluate(async (cmd: SaveCommand) => {
      const WPP = (window as any).WPP;
      if (!WPP?.contact?.save) return { code: 'contact_not_available' };
      try {
        const contact = await WPP.contact.save(cmd.id, cmd.name, {
          lastName: cmd.lastName,
          syncAddressBook: cmd.syncAddressBook,
        });
        return {
          isMyContact: !!contact?.isMyContact,
          syncToAddressbook: !!contact?.syncToAddressbook,
        };
      } catch (error: any) {
        return { code: String(error?.code || '') };
      }
    }, command);
    if (result?.code !== undefined) return fail(res, result);
    return res.status(200).json({ status: 'success', response: result });
  } catch (error: any) {
    return fail(res, error);
  }
}

export async function removeContact(req: Request, res: Response) {
  const id = toWid(req.body?.phone);
  if (!id) return fail(res, { code: 'contact_invalid' });
  const page = livePage(req, res);
  if (!page) return;
  try {
    const result = await page.evaluate(async (contactId: string) => {
      const WPP = (window as any).WPP;
      if (!WPP?.contact?.remove) return { code: 'contact_not_available' };
      try {
        await WPP.contact.remove(contactId);
        return {};
      } catch (error: any) {
        // WPPError carries its own code (contact_not_found, number_is_not_your_contact).
        return { code: String(error?.code || '') };
      }
    }, id);
    if (result?.code !== undefined) return fail(res, result);
    return res.status(200).json({ status: 'success', response: { message: 'Contact removed' } });
  } catch (error: any) {
    return fail(res, error);
  }
}
