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
import openerp.sql_db as sql_db
from openerp import pooler
import openerp.tools as tools
import openerp.exceptions
from openerp.tools.translate import _
from openerp.addons.base.ir.ir_cron import _intervalTypes
import datetime
import time
import subprocess
from urlparse import urlparse
import os
import glob
import shutil
import logging

try:
    import paramiko
    paramiko_installed = True
except:
    # ssh/sftp support disabled
    paramiko_installed = False
try:
    from ftplib import FTP
    ftplib_installed = True
except:
    # ftp support disabled
    ftplib_installed = False

_logger = logging.getLogger(__name__)

FREQ_TYPE = [('minutes', 'Minutes'), ('hours', 'Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')]
NOTIFICATION_MODES = [('failed', 'Failed'), ('always', 'Always')]

class oe_autobackup_config(osv.TransientModel):
    _name = "oe.autobackup.config"
    _inherit = 'res.config.settings'
    _description = ""
    _columns = {
        'folder': fields.char('Main Backup Folder', required=True),
        'copy_folder': fields.char('External Last Backup Folder'),
        'user_id': fields.many2one('res.users', string='Notify to', ondelete='restrict'),
        'notification_mode':fields.selection(NOTIFICATION_MODES, "Notification Mode"),
        'active': fields.boolean("Active"),
        'backup_ids': fields.many2many("oe.autobackup", "autobackup_config_autobackup_rel",
            'conf_id', 'backup_id', "Backups"),
    }

    def set_folder(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        #if not os.path.isdir(config.folder):
        #    raise osv.except_osv(_('Error!'),
        #            _('Path %s not found. Please set a valid folder' % config.folder) )
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'folder', config.folder)
        self.pool.get('ir.config_parameter').set_param(cr, uid, 'oe.autobackup.folder', config.folder)
        return True

    def set_copy_folder(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'copy_folder', config.copy_folder)
        self.pool.get('ir.config_parameter').set_param(cr, uid, 'oe.autobackup.copy_folder', config.folder)
        return True

    def set_user_id(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'user_id', config.user_id.id)
        return True

    def set_notification_mode(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        self.pool.get('ir.values').set_default(cr, uid, 'oe.autobackup', 'notification_mode', config.notification_mode)
        return True

    def default_get(self, cr, uid, fields, context=None):
        res = super(oe_autobackup_config, self).default_get(cr, uid, fields, context=context)
        res.update(self._defaults)
        ir_values_obj = self.pool.get('ir.values')
        for field, ftype in [("frequency", int), ("history_count", int), ("folder", str), ("copy_folder", str), ("notification_mode", str), ("user_id", int)]:
            res[field] = ir_values_obj.get_default(cr, uid, 'oe.autobackup', field)
        res['backup_ids'] = self.pool.get('oe.autobackup').search(cr, uid, [])
        return res

    def execute(self, cr, uid, data, context=None):
        _logger.debug("Create CONFIG called: %s" % data)
        return super(oe_autobackup_config, self).execute(cr, uid, data, context=context)

class oe_autobackup_file(osv.TransientModel):
    _name = "oe.autobackup.file"
    _columns = {
        'id': fields.integer("Id"),
        'autobackup_id': fields.many2one("oe.autobackup", "Auto Backup Job", required=True),
        'full_name': fields.char('File Name'),
        'create_time': fields.datetime("Created"),
        'size': fields.integer("Size"),
    }

    def get_files(self, cr, uid, autobackup_id, folder):
        _logger.debug("Scanning %s for path %s" % (folder, "%s_*.dump" % cr.dbname))
        files = glob.glob(os.path.join(folder, "%s_*.dump" % cr.dbname))
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

    def restore(self, cr, uid, ids, context=None):
        filedata = self.browse(cr, uid, ids)[0]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'oe.autobackup.restore',
            'view_mode': 'form',
            'view_type': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_filename': filedata.full_name
            }
        }

class FileCopy:
    def __init__(self, urlparsed, dbname):
        self.options = []
        self.urlparsed = urlparsed
        self.dbname = dbname

    def set_options(self, options):
        self.options = options[:]

    def initialize(self):
        raise NotImplemented()

    def copy(self, fromfile, tofile):
        raise NotImplemented()

    def rotate(self, folder, howmany):
        raise NotImplemented()

class LocalFileCopy(FileCopy):
    def initialize(self):
        path = os.path.join(self.options['basepath'], self.dbname)
        if not os.path.isdir(path):
            os.mkdir(path)

    def copy(self, fromfile, tofile):
        shutil.copy(fromfile, tofile)

    def rotate(self, folder, howmany):
        files = glob.glob(os.path.join(folder, "%s_*.dump" % self.dbname))
        files.sort(key=os.path.getmtime, reverse=True)
        _logger.debug("Found previous dumps of %s to keep: %s" % (howmany, files))
        for f in files[howmany:]:
            _logger.debug("removing file: %s" % f)
            os.unlink(f)

class FTPFileCopy(FileCopy):
    def initialize(self):
        if not ftplib_installed:
            raise Exception("Cannot use ftp. Missing required dependency to allow ftp: ftplib. Please install ftplib")

class SCPFileCopy(FileCopy):
    def initialize(self):
        if not paramiko_installed:
            raise Exception("Cannot use scp. Missing required dependency to allow scp: paramiko. Please install paramiko")

class RSyncFileCopy(FileCopy):
    def copy(self, fromfile, tofile):
        pass

class SFTPFileCopy(FileCopy):
    def __init__(self, urlparsed):
        self.port = urlparsed.port or 22
        self.host = urlparsed.host or 'localhost'
        self.username = urlparsed.username
        self.password = urlparsed.password
        self.pkey = None

    def set_options(self, options):
        pass

    def initialize(self):
        if not paramiko_installed:
            raise Exception("Cannot use scp. Missing required dependency to allow scp: paramiko. Please install paramiko")

    def copy(self, fromfile, tofile):
        transport = paramiko.Transport((self.host, self.port))
        connect_params = {
            'username': self.username,
            'host': self.host,
        }
        if self.password:
            connect_params['password'] = self.password
        if self.pkey:
            connect_params['pkey'] = self.pkey
        transport.connect(**connect_params)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(fromfile, tofile)
        sftp.close()
        transport.close()

def parse_external_folder(folder):
    fc = None
    parsed = urlparse(folder)
    if not parsed.scheme and not parsed.hostname: 
        # standard copy
        fc = LocalFileCopy(parsed)
    if parsed.scheme in KNOWN_SCHEME:
        fc = KNOWN_SCHEME[parsed.scheme](parsed)
    else:
        raise Exception("Unknown copy method in url: %s" % folder)
    return fc

def exec_pg_command_pipe(name, *args):
    prog = tools.find_pg_tool(name)
    if not prog:
        raise Exception('Couldn\'t find %s' % name)
    # on win32, passing close_fds=True is not compatible
    # with redirecting std[in/err/out]
    _logger.info("Exeuting PIPE command: %s" % ' '.join((prog,) + args))
    try:
        pop = subprocess.Popen((prog,) + args, bufsize=1,
          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
          close_fds=(os.name=="posix"), env=os.environ)
        return pop
        #subprocess.check_call((prog,) + args, shell=True)
    except Exception, ex:
        _logger.exception(ex)
        _logger.warn(ex.output)
        raise

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
        #'dbname': fields.char('DBName', required=True),
        'dump_extra_params': fields.char('Dump Extra Parameters'),
        'frequency': fields.integer("Backup Frequency", required=True),
        'frequency_type': fields.selection( FREQ_TYPE, 'Frequency Unit', required=True),
        'history_count': fields.integer("Backup History", help="Number of backup file to keep. 0 to disable rotation"),
        'folder': fields.char('Main Backup Folder', required=True),
        'copy_folder': fields.char('External Backup Folder'),
        'cron_id': fields.many2one('ir.cron', 'Cron Job', help="Scheduler which process the request", readonly=True),
        'cron_nextcall': fields.related( 
            'cron_id', 
            'nextcall', 
            type="datetime", 
            string="Next Call", 
            relation="ir.cron", 
            required=False 
        ),
        'last_run_date': fields.datetime("Last Run Date", readonly=True),
        'last_state': fields.selection([('draft', 'Never Executed'), ('ok', 'Success'), ('ko', 'Failed')], 'Execution Status', readonly=True),
        'state': fields.selection([('running', 'Running'), ('notrunning', 'Not Running')], 'Status', readonly=True),
        'user_id': fields.many2one('res.users', string='Notify to', ondelete='restrict'),
        'notification_mode':fields.selection(NOTIFICATION_MODES, "Notification Mode"),
        'backup_files': fields.function(_get_backup_files, type='one2many', relation="oe.autobackup.file", string="Files", readonly=True),
        'active': fields.boolean("Active"),
    }
    _defaults = {
        'active': True,
        'last_state': 'draft',
        'state': 'notrunning',
    }
    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Backup Already Defined'),
    ]

    def _init_folder_struct(self, basepath, name):
        path = os.path.join(basepath, name)
        if not os.path.isdir(path):
            os.mkdir(path)

    def schedule(self, cr, uid, ids, context=None):
        ids = ids if isinstance(ids, list) else [ids]
        data = self.read(cr, uid, ids[0])
        cron_name = 'autobackup_%s' % data['name']
        cron_id = self.pool.get('ir.cron').search(cr, uid, [('name', '=', cron_name )])
        #nextcall = fields.datetime.context_timestamp(cr, uid, datetime.datetime.strptime(time.strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT), tools.DEFAULT_SERVER_DATETIME_FORMAT))
        nextcall = datetime.datetime.strptime(time.strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT), tools.DEFAULT_SERVER_DATETIME_FORMAT)
        _logger.debug("CALL: %s" % nextcall)
        nextcall = nextcall + _intervalTypes[data['frequency_type']](data['frequency'])
        _logger.debug("NEXT CALL: %s" % nextcall)
        #if not cron_id:
        cron_id = self.pool.get('ir.cron').create(cr, uid, {
            'name': cron_name,
            'model':'oe.autobackup', 
            'args': repr([[ids[0]]]), 
            'function':'run', 
            'priority':6, 
            'interval_number': data['frequency'],
            'interval_type': data['frequency_type'],
            'numbercall': 1,
            'doall': 1,
            'user_id':uid,
            'nextcall': nextcall,
        })
        """
        else:
            cron_id = cron_id[0]
            self.pool.get('ir.cron').write(cr, uid, [cron_id], {
                'model':'oe.autobackup', 
                'args': repr([[ids[0]]]), 
                'interval_number': data['frequency'],
                'interval_type': data['frequency_type'],
                'numbercall': 1,
                'doall': 1,
                'user_id':uid,
                'nextcall': nextcall,
            })
        """
        self.write(cr, uid, ids, {
            'cron_id': cron_id
        })
        _logger.debug("Cleaning old schedules")
        oldcron_ids = self.pool.get('ir.cron').search(cr, uid, [('name', '=', cron_name ), ('active', '=', False)])
        self.pool.get('ir.cron').unlink(cr, uid, oldcron_ids)

    def create(self, cr, uid, data, context=None):
        #if 'dbname' not in data:
        #    data['dbname'] = cr.dbname
        _logger.debug("Creating backup job: %s" % data)
        backupjob_id = super(oe_autobackup, self).create(cr, uid, data, context=context)
        self._init_folder_struct(data['folder'], data['name'])
        if 'copy_folder' in data and data['copy_folder']:
            self._init_folder_struct(data['copy_folder'], data['name'])
        self.schedule(cr, uid, [backupjob_id], context=context)
        return backupjob_id

    def unlink(self, cr, uid, ids, context=None):
        cron_obj = self.pool.get('ir.cron')
        cron_data = self.read(cr, uid, ids, fields=["cron_id"])
        cron_ids = [ c['cron_id'][0] for c in cron_data if 'cron_id' in c and c['cron_id']]
        if cron_ids:
            cron_obj.unlink(cr, uid, cron_ids)
        return super(oe_autobackup, self).unlink(cr, uid, ids, context=context) 
        
    def write(self, cr, uid, ids, vals, context=None):
        res = super(oe_autobackup, self).write(cr, uid, ids, vals, context=context)
        if 'frequency' in vals or 'frequency_type' in vals or 'name' in vals:
            cron_data = {}
            if 'frequency' in vals or 'frequency_type' in vals:
                self.schedule(cr, uid, ids)
            if 'name' in vals:
                cron_data['name'] = 'autobackup_%s' % vals['name']
                folders_data = self.read(cr, uid, ids, fields=["folder", "copy_folder"])
                folder = folders_data[0]['folder'] if len(folders_data) else ''
                copy_folder = folders_data[0]['copy_folder'] if len(folders_data) else ''
                self._init_folder_struct(folder, vals['name'])
                self._init_folder_struct(copy_folder, vals['name'])
        return res

    def _rotate(self, dbname, folder, howmany):
        files = glob.glob(os.path.join(folder, "%s_*.dump" % dbname))
        files.sort(key=os.path.getmtime, reverse=True)
        _logger.debug("Found previous dumps of %s to keep: %s" % (howmany, files))
        for f in files[howmany:]:
            _logger.debug("removing file: %s" % f)
            os.unlink(f)

    def send_email(self, cr, uid, ids, res, error_message, context=None):
        _logger.debug("Send email called: %s %s" % (res, error_message))
        ir_model_data = self.pool.get('ir.model.data')
        template_id = ir_model_data.get_object_reference(cr, uid, 'oe_autobackups', 'email_template_edi_oe_autobackup')[1]
        email_obj = self.pool.get('email.template').send_mail(cr, uid, template_id, ids[0], force_send=True, context=context)
        _logger.debug("Email: %s" % email_obj)

    def run(self, cr, uid, ids, context=None):
        """Safe run with error management"""
        res = False
        error_message = ''

        new_cr = pooler.get_db(cr.dbname).cursor()
        config = self.browse(new_cr, uid, ids)[0]
        if config.state == 'running':
            _logger.warn("Autobackup %s already running: %s" % (config.name, config.last_run_date))
            return
        try:
            self.write(new_cr, uid, ids, {
                'state': 'running',
                'last_run_date': fields.datetime.now()
            })
            new_cr.commit()
            res = self._run(new_cr, uid, ids, context=context)
            _logger.info("Run finished: %s" % res)
        except Exception, ex:
            _logger.exception("Autobackup %s (%s) exception" % (config.name, config.last_run_date))
            _logger.exception(ex)
            error_message = str(ex)
        status = 'ok' if res else 'ko'
        _logger.debug("Writing scheduler state: %s" % status)
        self.write(new_cr, uid, ids, {
            'last_state': status
        })
        if config.notification_mode == 'always' or  status == 'ko':
            self.send_email(new_cr, uid, ids, res, error_message, context=context)
        new_cr.commit()
        _logger.debug("Setting backup to notrunning state")
        self.write(new_cr, uid, ids, {
            'state': 'notrunning'
        })
        new_cr.commit()
        _logger.debug("Scheduling next call")
        self.schedule(cr, uid, ids)
        return 

    def _run(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids)[0]
        _logger.info("Running dump with config: %s %s" % (config.last_run_date, config.cron_id.nextcall))
        dbname = cr.dbname
        filename = "%(db)s_%(timestamp)s.dump" % {
                'db': dbname,
                'timestamp': datetime.datetime.utcnow().strftime(
                    "%Y-%m-%d_%H-%M-%SZ")
                }
        dump_filename = os.path.join(config.folder, config.name, filename)
        self.do_dump(dbname, dump_filename, config.dump_extra_params)
        _logger.info('Scheduled Autobackup %s successful: %s', (config.name, dbname))
        if config.copy_folder:
            copy_filename = os.path.join(config.copy_folder, config.name, '%s.last.dump' % dbname)
            shutil.copy(dump_filename, copy_filename)
        if config.history_count:
            self._rotate(dbname, os.path.join(config.folder, config.name), config.history_count)
        return True

    def do_dump(self, db_name, dump_filename, extra_params=None):
        os.environ['PGPASSWORD'] = tools.config['db_password']
        #cmd = [os.path.join(tools.config['pg_path'], 'pg_dump'), '--format=c', '--no-owner']
        cmd = ['pg_dump', '--format=c', '--no-owner', '--file=%s' % dump_filename]
        if tools.config['db_user']:
            cmd.append('--username=' + tools.config['db_user'])
        if tools.config['db_host']:
            cmd.append('--host=' + tools.config['db_host'])
        if tools.config['db_port']:
            cmd.append('--port=' + str(tools.config['db_port']))
        if extra_params:
            cmd.extend(extra_params.split())
        cmd.append(db_name)
        _logger.info("Executing dump command: %s" % ' '.join(cmd))
        pop = exec_pg_command_pipe(*tuple(cmd))
        stdin, stdout = pop.stdin, pop.stdout
        stdin.close()
        output = stdout.read()
        _logger.debug("STDOUT: %s %s" % (output, os.environ))
        res = stdout.close()
        pop.wait()
        if res:
            _logger.error(
                    'DUMP DB: %s failed! Please verify the configuration of the database password on the server. '
                    'You may need to create a .pgpass file for authentication, or specify `db_password` in the '
                    'server configuration file.\n %s %s', db_name, output)
            raise Exception("Couldn't dump database: %s" % output)
        return res

class oe_autobackup_restore(osv.TransientModel):
    _name = "oe.autobackup.restore"
    _columns = {
        'dbname': fields.char('DB name', required=True),
        'filename': fields.char('Backup filename', required=True),
        'message': fields.char('Message'),
    }
    _defaults = {
        'message': 'Restore database backup file',
    }

    def _db_exist(self, db_name):
        return bool(sql_db.db_connect(db_name))

    def _create_empty_database(self, name):
        db = sql_db.db_connect('postgres')
        cr = db.cursor()
        chosen_template = tools.config['db_template']
        cr.execute("""SELECT datname 
                              FROM pg_database
                              WHERE datname = %s """,
                           (name,))
        if cr.fetchall():
            raise openerp.exceptions.Warning(" %s database already exists!" % name )
        try:
            cr.autocommit(True) # avoid transaction block
            cr.execute("""CREATE DATABASE "%s" ENCODING 'unicode' TEMPLATE "%s" """ % (name, chosen_template))
        finally:
            cr.close()

    def restore(self, cr, uid, ids, context=None):
        _logger.debug("RESTORE CALLED: %s - %s" % (ids, context))
        config = self.browse(cr, uid, ids)[0]
        if self._db_exist(config.dbname):
            _logger.warning('RESTORE DB: %s already exists', config.dbname)
            raise Exception("Database %s already exists" % config.dbname) 
        os.environ['PGPASSWORD'] = tools.config['db_password']
        self._create_empty_database(config.dbname)
        cmd = ['pg_restore', '--no-owner', '-c' ]
        if tools.config['db_user']:
            cmd.append('--username=' + tools.config['db_user'])
        if tools.config['db_host']:
            cmd.append('--host=' + tools.config['db_host'])
        if tools.config['db_port']:
            cmd.append('--port=' + str(tools.config['db_port']))
        cmd.append('--dbname=' + config.dbname)
        cmd.append('"%s"' % config.filename)
        _logger.info("Exeuting restore command: %s" % ' '.join(cmd))
        pop = exec_pg_command_pipe(*tuple(cmd))
        stdin, stdout = pop.stdin, pop.stdout
        stdin.close()
        output = stdout.read()
        _logger.info("STDOUT: %s %s" % (output, os.environ))
        res = stdout.close()
        if res:
            raise Exception("Couldn't restore database: %s" % output)
        _logger.info('RESTORED DB: %s', config.dbname)
        self.write(cr, uid, ids, {
            'message': 'Database %s restored successfully' % config.dbname
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'oe.autobackup.restore',
            'res_id': ids[0],
            'view_mode': 'form',
            'view_type': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }


