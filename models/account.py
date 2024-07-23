# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

import base64
import logging
import json
import requests

class AccountMove(models.Model):
    _inherit = "account.move"

    pdf_fel = fields.Binary('PDF FE', copy=False)
    pdf_fel_name = fields.Char('Nombre PDF FE', default='pdf_fel.pdf', size=32)

    def _post(self, soft=True):
        if self.certificar_cr():
            return super(AccountMove, self)._post(soft)

    def post(self):
        if self.certificar_cr():
            return super(AccountMove, self).post()
    
    def certificar_cr(self):
        for factura in self:
            logging.warning('certificar_cr');
            if factura.requiere_certificacion_cr('gticr'):

                if factura.error_pre_validacion_cr():
                    return
                    
                #factura.descuento_lineas()
                
                completo = {}
                completo['NumCuenta'] = factura.company_id.numero_cuenta_fel
                
                doc = {}
                completo['Documentos'] = [doc]
                
                doc['Encabezado'] = {}
                doc['Encabezado']['FechaFactura'] = factura.invoice_date.strftime('%Y-%m-%dT00:00:00') if factura.invoice_date else fields.Date.context_today(self).strftime('%Y-%m-%dT00:00:00')
                
                tipo_documento_fel = factura.journal_id.tipo_documento_cr_fel
                tipo_interno_factura = factura.type if 'type' in factura.fields_get() else factura.move_type
                if tipo_documento_fel in ['1', '4'] and tipo_interno_factura == 'out_refund':
                    tipo_documento_fel = '3'
                
                doc['Encabezado']['TipoDoc'] = int(tipo_documento_fel)
                doc['Encabezado']['SituacionEnvio'] = 1
                doc['Encabezado']['CantDeci'] = 2
                doc['Encabezado']['Sucursal'] = factura.journal_id.sucursal_fel
                doc['Encabezado']['Terminal'] = factura.journal_id.terminal_fel
                doc['Encabezado']['CodigoActividad'] = factura.journal_id.codigo_actividad_fel

                moneda = 1
                if factura.currency_id.id != factura.company_id.currency_id.id:
                    moneda = 2

                doc['Encabezado']['Moneda'] = moneda
                doc['Encabezado']['MedioPago'] = [4]
                doc['Encabezado']['CondicionVenta'] = 2
                    
                doc['Encabezado']['Receptor'] = {}
                doc['Encabezado']['Receptor']['Nombre'] = factura.partner_id.name
                doc['Encabezado']['Receptor']['TipoIdent'] = factura.partner_id.tipo_identificacion_fel
                doc['Encabezado']['Receptor']['Identificacion'] = factura.partner_id.vat
                if factura.partner_id.phone and len(factura.partner_id.phone.split()) > 2:
                    doc['Encabezado']['Receptor']['AreaTelefono'] = factura.partner_id.phone.split()[0]
                    doc['Encabezado']['Receptor']['NumTelefono'] = factura.partner_id.phone.split()[1]
                doc['Encabezado']['Receptor']['CodInterno'] = factura.partner_id.ref
                if factura.partner_id.street:
                    doc['Encabezado']['Receptor']['Direccion'] = factura.partner_id.street or '-'
                if factura.partner_id.provincia_fel:
                    doc['Encabezado']['Receptor']['Provincia'] = int(factura.partner_id.provincia_fel)
                if factura.partner_id.canton_fel:
                    doc['Encabezado']['Receptor']['Canton'] = int(factura.partner_id.canton_fel)
                if factura.partner_id.distrito_fel:
                    doc['Encabezado']['Receptor']['Distrito'] = int(factura.partner_id.distrito_fel)
                if factura.partner_id.barrio_fel:
                    doc['Encabezado']['Receptor']['Barrio'] = int(factura.partner_id.barrio_fel)

                doc['Lineas'] = []

                num = 1
                total_global_mercaderia = 0
                total_global_servicio = 0
                total_global_descuento = 0
                total_global_impuestos = 0
                
                for linea in factura.invoice_line_ids:
                    if linea.price_total == 0:
                        continue
                    
                    tipo_producto = 'B'
                    if linea.product_id.type == 'service':
                        tipo_producto = 'S'
                        
                    codigo = linea.product_id.codigo_cabys_fel
                                            
                    precio_unitario = linea.price_unit * (100-linea.discount) / 100
                    precio_sin_descuento = linea.price_unit
                    descuento = precio_sin_descuento * linea.quantity - precio_unitario * linea.quantity
                    precio_unitario_base = linea.price_subtotal / linea.quantity
                    total_linea = linea.price_total
                    total_linea_base = linea.price_subtotal
                    total_impuestos = total_linea - total_linea_base
                    
                    if tipo_producto == 'B':
                        #total_global_mercaderia += linea.price_unit * linea.quantity
                        total_global_mercaderia += total_linea
                    else:
                        #total_global_servicio += linea.price_unit * linea.quantity
                        total_global_servicio += total_linea
                    total_global_descuento += descuento
                    total_global_impuestos += total_impuestos
                    
                    detalle = {}
                    detalle['Codigo'] = codigo
                    detalle['Cantidad'] = '{:.6f}'.format(linea.quantity)
                    detalle['UnidadMedida'] = linea.product_uom_id.codigo_fel or '1'
                    detalle['Descripcion'] = linea.name
                    detalle['PrecioUnitario'] = '{:.6f}'.format(precio_sin_descuento)
                    detalle['Descuentos'] = [{
                        'MontoDescuento': '{:.2f}'.format(descuento),
                        'DetalleDescuento': 'Se aplica descuento.'
                    }]
                    
                    detalle['Impuestos'] = [{
                        'CodigoImp': 1,
                        'CodigoTarifa': 8,
                        'MontoImp': total_impuestos,
                    }]
                    
                    doc['Lineas'].append(detalle)
                    
                doc['Totales'] = {}
                doc['Totales']['TotalServGravado'] = total_global_servicio
                doc['Totales']['TotalServExento'] = 0
                doc['Totales']['TotalServExonerado'] = 0
                doc['Totales']['TotalMercaGravada'] = total_global_mercaderia
                doc['Totales']['TotalMercaExenta'] = 0
                doc['Totales']['TotalMercaExonerada'] = 0
                doc['Totales']['TotalGravado'] = total_global_servicio + total_global_mercaderia
                doc['Totales']['TotalExento'] = 0
                doc['Totales']['TotalExonerado'] = 0
                doc['Totales']['TotalIVADevuelto'] = 0
                doc['Totales']['TotalOtrosCargos'] = 0
                doc['Totales']['TotalVenta'] = total_global_servicio + total_global_mercaderia
                doc['Totales']['TotalDescuento'] = total_global_descuento
                doc['Totales']['TotalVentaNeta'] = total_global_servicio + total_global_mercaderia - total_global_descuento
                doc['Totales']['TotalImpuesto'] = total_global_impuestos
                #doc['Totales']['TotalComprobante'] = total_global_servicio + total_global_mercaderia + total_global_impuestos
                doc['Totales']['TotalComprobante'] = total_global_servicio + total_global_mercaderia

                logging.warning(json.dumps(completo, sort_keys=True, indent=4))
                
                r = requests.post("https://pruebas.gticr.com/AplicacionFEPruebas/ApiCargaFactura/api/Documentos/CargarDocumento?pUsuario={}&pClave={}&pNumCuenta={}".format(factura.company_id.usuario_fel, factura.company_id.clave_fel, factura.company_id.numero_cuenta_fel), json=completo)
                logging.warning(r.text)
                
                resultado = r.json()

                if 'Respuestas' in resultado and len(resultado['Respuestas']) > 0 and 'Consecutivo' in resultado['Respuestas'][0]:
                    factura.consecutivo_fel = resultado['Respuestas'][0]['Consecutivo']
                    factura.clave_numerica_fel = resultado['Respuestas'][0]['ClaveNumerica']
                    factura.certificador_fel = "gti"
                else:
                    factura.error_certificador(r.text)
                    return False

                return True

            else:
                return True
        
#    def button_cancel(self):
#        result = super(AccountMove, self).button_cancel()
#        for factura in self:
#            if factura.requiere_certificacion() and factura.firma_fel:
#                
#                wsdl = "https://www.facturaenlineagt.com/aanulacion?wsdl"
#                if factura.company_id.pruebas_fel:
#                    wsdl = "http://pruebas.ecofactura.com.gt:8080/fel/aanulacion?wsdl"
#                client = zeep.Client(wsdl=wsdl)
#                
#                resultado = client.service.Execute(factura.company_id.vat, factura.company_id.usuario_fel, factura.company_id.clave_fel, factura.company_id.vat, factura.firma_fel, factura.motivo_fel)
#                logging.warn(resultado)
#                resultadoBytes = bytes(bytearray(resultado, encoding='utf-8'))
#                resultadoXML = etree.XML(resultadoBytes)
#                factura.pdf_fel = resultadoXML.xpath("/DTE/Pdf")[0].text
#                logging.warn(resultado)
#
#                if not resultadoXML.xpath("/DTE"):
#                    raise ValidationError(resultado)
                                                
class AccountJournal(models.Model):
    _inherit = "account.journal"
    
    sucursal_fel = fields.Char('Sucursal FE')
    terminal_fel = fields.Char('Terminal FE')

class ResCompany(models.Model):
    _inherit = "res.company"

    numero_cuenta_fel = fields.Char('Numero de Cuenta FE')
    usuario_fel = fields.Char('Usuario FE')
    clave_fel = fields.Char('Clave FE')
    pruebas_fel = fields.Boolean('Pruebas FE')
    certificador_cr_fel = fields.Selection(selection_add=[('gticr', 'GTICR')])
