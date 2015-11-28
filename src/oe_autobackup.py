#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2015 antonio <me.verni@gmail.com>
#
# Distributed under terms of the MIT license.

"""
"""

from openerp.osv import osv, fields, orm
import openerp.tools as tools
from openerp.tools.translate import _
import datetime
import subprocess
import os
import glob
import shutil
import logging

_logger = logging.getLogger(__name__)

freq_type = [('minutes', 'Minutes'), ('hours', 'Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')]

class oe_autobackup_config(osv.TransientModel):
    _name = "oe.autobackup.config"
    _inherit = 'res.config.settings'
    _description = ""
    _columns = {
        'frequency': fields.integer("Hourly Backup Frequency"),
        'frequency_type': fields.selection( freq_type, 'Frequency Unit'),
        'history_count': fields.integer("Backup History"),
        'password': fields.char('Database Password'),
        'folder': fields.char('Main Backup Folder', required=True),
        'copy_folder': fields.char('External Last Backup Folder'),
        'active': fields.boolean("Active"),
        'backup_ids': fields.many2many("oe.autobackup", "autobackup_config_autobackup_rel",
            'conf_id', 'backup_id', "Backups"),
    }
    _defaults = {
        'history_count': 5,
        'frequency': 1,
        'frequency_type': 'hourly',
    }

    def set_password(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'password', config.password)
        return True

    def set_frequency(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'frequency', config.frequency)
        return True

    def set_frequency_type(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'frequency_type', config.frequency_type)
        return True

    def set_history_count(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'history_count', config.history_count)
        return True

    def set_folder(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        if not os.path.isdir(config.folder):
            raise osv.except_osv(_('Error!'),
                    _('Path %s not found. Please set a valid folder' % config.folder) )
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'folder', config.folder)
        return True

    def set_copy_folder(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'copy_folder', config.copy_folder)
        return True


    def default_get(self, cr, uid, fields, context=None):
        res = super(oe_autobackup_config, self).default_get(cr, uid, fields, context=context)
        res.update(self._defaults)
        ir_values_obj = self.pool.get('ir.values')
        for field, ftype in [("frequency", int), ("history_count", int), ("folder", str), ("copy_folder", str), ('password', str)]:
            res[field] = ir_values_obj.get_default(cr, uid, 'oe.autobackup', field)
        res['backup_ids'] = self.pool.get('oe.autobackup').search(cr, uid, [])
        return res

    def execute(self, cr, uid, data, context=None):
        _logger.debug("Create CONFIG called: %s" % data)
        return super(oe_autobackup_config, self).execute(cr, uid, data, context=context)

def exec_pg_command_pipe(name, *args):
    prog = tools.find_pg_tool(name)
    if not prog:
        raise Exception('Couldn\'t find %s' % name)
    # on win32, passing close_fds=True is not compatible
    # with redirecting std[in/err/out]
    pop = subprocess.Popen((prog,) + args, bufsize= -1,
          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
          close_fds=(os.name=="posix"))
    return pop.stdin, pop.stdout

class oe_autobackup_file(osv.TransientModel):
    _name = "oe.autobackup.file"
    _columns = {
        'autobackup_id': fields.many2one("oe.autobackup", "Auto Backup Job", required=True),
        'full_name': fields.char('File Name'),
        'create_time': fields.datetime("Created"),
        'size': fields.integer("Size"),
    }

    def get_files(self, cr, uid, autobackup_id, folder):
        files = glob.glob(os.path.join(folder, "*.dump"))
        files.sort(key=os.path.getmtime, reverse=True)
        res = []
        for f in files:
            fstat = os.stat(f)
            ctime = datetime.datetime.fromtimestamp(fstat.st_ctime)
            fdata = {
                'autobackup_id': autobackup_id,
                'full_name': f,
                'create_time': ctime.strftime("%Y-%m-%d %H:%M:%S"),
                'size': fstat.st_size,
            }
            file_id = self.create(cr, uid, fdata)
            res.append(file_id)
        return res

class oe_autobackup(osv.Model):
    _name = "oe.autobackup"

    def _get_backup_files(self, cr, uid, ids, field_name, arg=None, context=None):
        res = {}
        files_obj = self.pool.get('oe.autobackup.file')
        for obj in self.browse(cr, uid, ids):
            backup_folder = os.path.join(obj.folder, obj.name)
            res[obj.id] = files_obj.get_files(cr, uid, obj.id, backup_folder)
        return res

    _rec_name = "name"
    _columns = {
        'name': fields.char('Name', required=True),
        'password': fields.char('Database Password'),
        'frequency': fields.integer("Backup Frequency", required=True),
        'frequency_type': fields.selection( freq_type, 'Frequency Unit', required=True),
        'history_count': fields.integer("Backup History"),
        'folder': fields.char('Main Backup Folder', required=True),
        'copy_folder': fields.char('External Backup Folder'),
        'cron_id': fields.many2one('ir.cron', 'Cron Job', help="Scheduler which process the request", readonly=True),
        'last_run_date': fields.datetime("Last Run Date", readonly=True),
        'backup_files': fields.function(_get_backup_files, type='one2many', relation="oe.autobackup.file", string="Files", readonly=True),
        'active': fields.boolean("Active"),
    }
    _defaults = {
        'active': True,
    }
    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Backup Already Defined'),
    ]

    def _init_folder_struct(self, basepath, name):
        path = os.path.join(basepath, name)
        if not os.path.isdir(path):
            os.mkdir(path)

    def create(self, cr, uid, data, context=None):
        backupjob_id = super(oe_autobackup, self).create(cr, uid, data, context=context)
        self._init_folder_struct(data['folder'], data['name'])
        if 'copy_folder' in data and data['copy_folder']:
            self._init_folder_struct(data['copy_folder'], data['name'])
        cron_name = 'autobackup_%s' % data['name']
        cron_id = self.pool.get('ir.cron').search(cr, uid, [('name', '=', cron_name )])
        if not cron_id:
            res = {
                'name': cron_name,
                'model':'oe.autobackup', 
                'args': repr([[backupjob_id]]), 
                'function':'run', 
                'priority':6, 
                'interval_number': data['frequency'],
                'interval_type': data['frequency_type'],
                'numbercall': -1,
                'user_id':uid
            }
            cron_id = self.pool.get('ir.cron').create(cr, uid, res)
        else:
            cron_id = cron_id[0]
        self.write(cr, uid, backupjob_id, {
            'cron_id': cron_id
        }, context=context)
        return backupjob_id

    def unlink(self, cr, uid, ids, context=None):
        cron_obj = self.pool.get('ir.cron')
        cron_data = self.read(cr, uid, ids, fields=["cron_id"])
        cron_ids = [ c['cron_id'][0] for c in cron_data if 'cron_id' in c and c['cron_id']]
        cron_obj.unlink(cr, uid, cron_ids)
        return super(oe_autobackup, self).unlink(cr, uid, ids, context=context) 
        
    def write(self, cr, uid, ids, vals, context=None):
        res = super(oe_autobackup, self).write(cr, uid, ids, vals, context=context)
        if 'frequency' in vals or 'frequency_type' in vals or 'name' in vals:
            cron_data = {}
            if 'frequency' in vals:
                cron_data['interval_number'] = vals['frequency']
            if 'frequency_type' in vals:
                cron_data['interval_type'] = vals['frequency_type']
            if 'name' in vals:
                cron_data['name'] = 'autobackup_%s' % vals['name']
                folders_data = self.read(cr, uid, ids, fields=["folder", "copy_folder"])
                folder = folders_data[0]['folder'] if len(folders_data) else ''
                copy_folder = folders_data[0]['copy_folder'] if len(folders_data) else ''
                self._init_folder_struct(folder, vals['name'])
                self._init_folder_struct(copy_folder, vals['name'])
            cron_ids = self.read(cr, uid, ids, fields=["cron_id"])
            self.pool.get("ir.cron").write(cr, uid, [c['cron_id'][0] for c in cron_ids], cron_data)
        return res

    def _rotate(self, folder, howmany):
        files = glob.glob(os.path.join(folder, "*.dump"))
        files.sort(key=os.path.getmtime, reverse=True)
        _logger.debug("Found previous dumps of %s to keep: %s" % (howmany, files))
        for f in files[howmany:]:
            _logger.debug("removing file: %s" % f)
            os.unlink(f)

    def run(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        _logger.debug("Running dump with config: %s" % config)
        self.write(cr, uid, ids, {
            'last_run_date': fields.datetime.now()
        })

        filename = "%(db)s_%(timestamp)s.dump" % {
                'db': cr.dbname,
                'timestamp': datetime.datetime.utcnow().strftime(
                    "%Y-%m-%d_%H-%M-%SZ")
                }
        dump_filename = os.path.join(config.folder, config.name, filename)
        data = self.do_dump(cr.dbname, config.password)
        _logger.info('Scheduled Autobackup %s successful: %s', (config.name, cr.dbname))
        fp = open(dump_filename, "w")
        fp.write(data)
        fp.close()
        _logger.debug("Created Dump filename: %s" % dump_filename)
        if config.copy_folder:
            copy_filename = os.path.join(config.copy_folder, config.name, '%s.last.dump' % cr.dbname)
            shutil.copy(dump_filename, copy_filename)
        self._rotate(os.path.join(config.folder, config.name), config.history_count)
        return True

    def do_dump(self, db_name, password):
        os.environ['PGPASSWORD'] = password
        cmd = ['pg_dump', '--format=c', '--no-owner']
        if tools.config['db_user']:
            cmd.append('--username=' + tools.config['db_user'])
        if tools.config['db_host']:
            cmd.append('--host=' + tools.config['db_host'])
        if tools.config['db_port']:
            cmd.append('--port=' + str(tools.config['db_port']))
        cmd.append(db_name)
        stdin, stdout = exec_pg_command_pipe(*tuple(cmd))
        stdin.close()
        data = stdout.read()
        res = stdout.close()
        if not data or res:
            _logger.error(
                    'DUMP DB: %s failed! Please verify the configuration of the database password on the server. '
                    'You may need to create a .pgpass file for authentication, or specify `db_password` in the '
                    'server configuration file.\n %s %s', db_name, data)
            raise Exception, "Couldn't dump database"
        return data
    

