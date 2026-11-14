/* Xiaomi service-session exchange. No browser input automation and no logging.
 * Protocol route reference: Zhou-Ruichen/mi-health-mcp (passToken exchange).
 */
const ACCOUNT='https://account.xiaomi.com';
const SID='miothealth';
const LOGIN_UA='Dalvik/2.1.0 (Linux; U; Android 12; V2284A Build/ab8c0d1.1) APP/mi.health APPV/359002 MK/VjIyODRB SDKV/5.3.0.release.68 CPN/com.mi.health PassportSDK/';
class FlowError extends Error {
  constructor(code,details={}) { super(code);this.code=code;this.details=details; }
}
function domainMatches(host,domain) {
  domain=domain.replace(/^\./,'').toLowerCase();host=host.toLowerCase();
  return host===domain || host.endsWith('.'+domain);
}
function credentialsFromCookies(cookies) {
  const value=name=>cookies.find(c=>c.name===name && domainMatches('account.xiaomi.com',c.domain))?.value;
  const user_id=value('userId'),pass_token=value('passToken'),device_id=value('deviceId');
  return user_id && pass_token && device_id ? {user_id,pass_token,device_id} : null;
}
function cookieHeader(credentials) {
  for (const key of ['user_id','pass_token','device_id']) {
    if (typeof credentials[key]!=='string' || !credentials[key] || /[;\r\n]/.test(credentials[key]))
      throw new FlowError('INVALID_ACCOUNT_MATERIAL');
  }
  return `sdkVersion=3.9; userId=${credentials.user_id}; passToken=${credentials.pass_token}; deviceId=${credentials.device_id}`;
}
async function decode(response) {
  if (response.status()!==200) throw new FlowError('ACCOUNT_HTTP_ERROR',{http_status:response.status()});
  try {return JSON.parse((await response.text()).trim().replace(/^&&&START&&&/,''));}
  catch {throw new FlowError('ACCOUNT_RESPONSE_FORMAT');}
}
function validateLocation(value) {
  let url;try {url=new URL(value);} catch {throw new FlowError('INVALID_SERVICE_CALLBACK');}
  if (url.protocol!=='https:' || !(url.hostname.endsWith('.mi.com') || url.hostname.endsWith('.xiaomi.com')))
    throw new FlowError('INVALID_SERVICE_CALLBACK');
  return url;
}
function validateSession(session) {
  if (session?.sid!==SID) throw new FlowError('WRONG_SESSION_SERVICE');
  for (const key of ['user_id','c_user_id','service_token','ssecurity']) {
    if (typeof session[key]!=='string' || !session[key]) throw new FlowError('INCOMPLETE_SERVICE_SESSION');
  }
  if (session.service_token===SID) throw new FlowError('SERVICE_MARKER_IS_NOT_TOKEN');
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(session.ssecurity) || Buffer.from(session.ssecurity,'base64').length<16)
    throw new FlowError('INVALID_SERVICE_SECURITY');
  return session;
}
async function exchange(requestFactory,credentials,saveRecovery) {
  const cookie=cookieHeader(credentials);
  // Complete protected persistence before the first network operation.
  await saveRecovery(credentials);
  const api=await requestFactory({userAgent:LOGIN_UA,extraHTTPHeaders:{Cookie:cookie}});
  try {
    let result=await decode(await api.get(ACCOUNT+'/pass/serviceLogin?sid=miothealth&_json=true',
      {maxRedirects:0,timeout:20000}));
    if (!result.ssecurity && result._sign && result.callback && result.qs) {
      result=await decode(await api.post(ACCOUNT+'/pass/serviceLoginAuth2',{
        maxRedirects:0,timeout:20000,form:{user:credentials.user_id,sid:SID,_json:'true',
          callback:result.callback,_sign:result._sign,qs:result.qs,_parset:'true'}
      }));
    }
    if (result.code!==0) throw new FlowError('ACCOUNT_REJECTED',{account_code:result.code});
    if (!result.ssecurity || !result.location || !result.userId) throw new FlowError('APP_SESSION_MATERIAL_MISSING');
    if (String(result.userId)!==credentials.user_id) throw new FlowError('ACCOUNT_ID_MISMATCH');
    const location=validateLocation(result.location);
    const response=await api.get(location.href,{maxRedirects:0,timeout:25000,
      headers:{Cookie:`userId=${credentials.user_id}; passToken=${credentials.pass_token}; deviceId=${credentials.device_id}`}});
    if (response.status()<200 || response.status()>=400)
      throw new FlowError('SERVICE_CALLBACK_HTTP_ERROR',{http_status:response.status()});
    const cookies=(await api.storageState()).cookies;
    const candidates=cookies.filter(c=>c.name==='serviceToken' && c.value!==SID && domainMatches(location.hostname,c.domain));
    candidates.sort((a,b)=>b.domain.length-a.domain.length);
    const cUserId=result.cUserId || cookies.find(c=>c.name==='cUserId' && domainMatches(location.hostname,c.domain))?.value;
    return validateSession({sid:SID,user_id:String(result.userId),c_user_id:cUserId || '',
      service_token:candidates[0]?.value || '',ssecurity:result.ssecurity,time_diff_ms:0,obtained_at:new Date().toISOString()});
  } catch (error) {
    if (error instanceof FlowError) throw error;
    throw new FlowError('SESSION_NETWORK_ERROR');
  } finally {await api.dispose();}
}
module.exports={SID,FlowError,credentialsFromCookies,cookieHeader,domainMatches,exchange,validateSession};
