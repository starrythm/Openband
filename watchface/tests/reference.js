const readline = require('readline');
const A = require('../../vendor/astronomy-engine/astronomy.js');
const {latitude, longitude} = require('../observer.example.json');
const names = ['Sun','Moon','Mercury','Venus','Mars','Jupiter','Saturn','Uranus','Neptune'];
const observer = new A.Observer(latitude, longitude, 0);
readline.createInterface({input: process.stdin}).on('line', line => {
  const epoch = Number(line), date = new Date(epoch * 1000);
  for (const name of names) {
    const equ = A.Equator(A.Body[name], date, observer, true, true);
    const hor = A.Horizon(date, observer, equ.ra, equ.dec, 'normal');
    const phase = name === 'Moon' ? (1-Math.cos(A.MoonPhase(date)*Math.PI/180))/2 : -1;
    const mag = name === 'Sun' ? -100 : A.Illumination(A.Body[name],date).mag;
    console.log([epoch,name,hor.azimuth,hor.altitude,phase,mag].join(','));
  }
});
