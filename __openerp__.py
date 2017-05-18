# -*- coding: utf-8 -*-

{
	'name': 'OE AUTOBACKUPS',
	'version': '0.7',
	'category': 'Tools',
	'description': """
Auto Backup Manager
""",
	'author': 'Antonio Verni (me.verni@gmail.com)',
        'website': 'www.linkedin.com/in/averni',
	#'license': 'MIT',
	'depends': ["email_template"],
	'data': [
            'security/ir.model.access.csv',
            'views/oe_autobackup_view.xml',
            'edi/oe_autobackup_data.xml',
        ],
	'css' : [],
	'demo': [],
	'installable' : True,
}

