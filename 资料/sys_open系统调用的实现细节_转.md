# sys_open系统调用的实现细节（转）

————————————————
版权声明：本文为CSDN博主「mindlesslcc」的原创文章，遵循CC 4.0 BY-SA版权协议，转载请附上原文出处链接及本声明。
原文链接：https://blog.csdn.net/sanwenyublog/article/details/50880528

————————————————



打开一个文件，是通过内核提供的系统调用sys_open来实现的，在用户空间的open函数会被编译器编译成为int 80的汇编代码，进入内核空间执行打开操作，我们来顺着内核的代码来看一下具体的实现过程。
sys_open函数定义在fs/open.c文件，定义如下
asmlinkage long sys_open(const char __user *filename, int flags, int mode)
{
	long ret;
	/*检查内核是不是支持大文件，如果是大文件的话就对flags标记对应的标记位置位*/
	if (force_o_largefile())
		flags |= O_LARGEFILE;
	/*封装的操作*/
	ret = do_sys_open(AT_FDCWD, filename, flags, mode);
	/* 禁止编译器尾部优化 */
	prevent_tail_call(ret);
	return ret;
}


核心的操作都在do_sys_open(AT_FDCWD, filename, flags, mode);里边，其他的都只是检查一下参数是否合法，我们来看do_sys_open是怎么实现的吧，do_sys_open定义在fs/open.c文件，定义如下
long do_sys_open(int dfd, const char __user *filename, int flags, int mode)
{
	/*把用户空间的存在内存的文件名字符串复制到内核空间*/
	char *tmp = getname(filename);
	int fd = PTR_ERR(tmp);
 
 
	if (!IS_ERR(tmp)) {
		/*寻找一个暂时没用的文件描述符，或者没有的话返回错误*/
		fd = get_unused_fd();
		if (fd >= 0) {
			/*如果找到的话，就执行打开操作*/
			struct file *f = do_filp_open(dfd, tmp, flags, mode);
			if (IS_ERR(f)) {
				/*打开失败，就释放文件描述符*/
				put_unused_fd(fd);
				fd = PTR_ERR(f);
			} else {
				fsnotify_open(f->f_path.dentry);
				fd_install(fd, f);
			}
		}
		putname(tmp);
	}
	return fd;
}


然后我们继续看do_filp_open函数，do_filp_open函数定义在fs/open.c文件，定义如下
/*
 * 注意flag标记位低两位的意义:
 *	00 - read-only
 *	01 - write-only
 *	10 - read-write
 *	11 - special
 * 现在变成了
 *	00 - no permissions needed
 *	01 - read-permission
 *	10 - write-permission
 *	11 - read-write
 * for the internal routines (ie open_namei()/follow_link() etc). 00 is
 * used by symlinks.
 */
static struct file *do_filp_open(int dfd, const char *filename, int flags,
				 int mode)
{
	int namei_flags, error;
	struct nameidata nd;
	/*内外标记不一样*/
	namei_flags = flags;
	if ((namei_flags+1) & O_ACCMODE)
		namei_flags++;
	/*顺着文件名打开操作*/
	error = open_namei(dfd, filename, namei_flags, mode, &nd);
	if (!error)/*根据得到的文件数据，填充file结构体*/
		return nameidata_to_filp(&nd, flags);
 
 
	return ERR_PTR(error);
}


我们来逐个分析open_namei函数，open_namei函数定义在fs/namei.c，定义如下
int open_namei(int dfd, const char *pathname, int flag,
		int mode, struct nameidata *nd)
{
	int acc_mode, error;
	struct path path;
	struct dentry *dir;
	int count = 0;
	/*从flags得到打开模式*/
	acc_mode = ACC_MODE(flag);
 
 
	/* O_TRUNC表示我们需要检查写的权限 */
	if (flag & O_TRUNC)
		acc_mode |= MAY_WRITE;
 
 
	/*O_APPEND需要MAY_APPEND权限  */
	if (flag & O_APPEND)
		acc_mode |= MAY_APPEND;
 
 
	/*如果是不是创建文件的话，就调用path_lookup_open函数获得文件的dentry和vfsmount填充nameidata结构体，找到后就直接返回*/
	if (!(flag & O_CREAT)) {
		error = path_lookup_open(dfd, pathname, lookup_flags(flag),
					 nd, flag);
		/*获得后就直接返回函数*/
		if (error)
			return error;
		goto ok;
	}
 
 
	/*如果是要创建文件，我们需要知道父目录，所以加上LOOKUP_PARENT的flag*/
	error = path_lookup_create(dfd,pathname,LOOKUP_PARENT,nd,flag,mode);
	if (error)
		return error;
 
 
	/*已经拥有了父目录，我们检查下返回结果，如果最后找到的是目录就返回错误，我们只创建文件不创建目录 */
	error = -EISDIR;
	if (nd->last_type != LAST_NORM || nd->last.name[nd->last.len])
		goto exit;
	/**/
	dir = nd->dentry;
	nd->flags &= ~LOOKUP_PARENT;
	mutex_lock(&dir->d_inode->i_mutex);
	/*填充path结构体*/
	path.dentry = lookup_hash(nd);
	path.mnt = nd->mnt;
 
 
do_last:
	/*如果获得的参数有问题就返回错误*/
	error = PTR_ERR(path.dentry);
	if (IS_ERR(path.dentry)) {
		mutex_unlock(&dir->d_inode->i_mutex);
		goto exit;
	}
 
 
	if (IS_ERR(nd->intent.open.file)) {
		mutex_unlock(&dir->d_inode->i_mutex);
		error = PTR_ERR(nd->intent.open.file);
		goto exit_dput;
	}
 
 
	/* 错误的dentry，直接创建文件 */
	if (!path.dentry->d_inode) {
		error = open_namei_create(nd, &path, flag, mode);
		if (error)
			goto exit;
		return 0;
	}
 
 
	/*
	 * 说明文件已经存在
	 */
	mutex_unlock(&dir->d_inode->i_mutex);
	audit_inode(pathname, path.dentry->d_inode);
	/*O_EXCL标志代表如果文件存在就退出*/
	error = -EEXIST;
	if (flag & O_EXCL)
		goto exit_dput;
	/*找到真正的挂载点*/
	if (__follow_mount(&path)) {
		error = -ELOOP;
		if (flag & O_NOFOLLOW)
			goto exit_dput;
	}
 
 
	error = -ENOENT;
	/*说明创建失败*/
	if (!path.dentry->d_inode)
		goto exit_dput;
	/*处理连接*/
	if (path.dentry->d_inode->i_op && path.dentry->d_inode->i_op->follow_link)
		goto do_link;
	/*path结构体转成nameidata结构体*/
	path_to_nameidata(&path, nd);
	error = -EISDIR;
	/*再次检查*/
	if (path.dentry->d_inode && S_ISDIR(path.dentry->d_inode->i_mode))
		goto exit;
ok:
	/*写之前的一些检查和准备工作*/
	error = may_open(nd, acc_mode, flag);
	if (error)
		goto exit;
	return 0;
 
 
exit_dput:
	/*退出前释放path*/
	dput_path(&path, nd);
exit:
	if (!IS_ERR(nd->intent.open.file))
		release_open_intent(nd);
	path_release(nd);
	return error;
 
 
do_link:
	/*如果flag有O_NOFOLLOW，说明禁止链接，直接返回错误*/
	error = -ELOOP;
	if (flag & O_NOFOLLOW)
		goto exit_dput;
	/*首先找到父目录*/
	nd->flags |= LOOKUP_PARENT;
	/*安全操作，暂时不管*/
	error = security_inode_follow_link(path.dentry, nd);
	if (error)
		goto exit_dput;
	/*搜寻，并创建*/
	error = __do_follow_link(&path, nd);
	if (error) {
		release_open_intent(nd);
		return error;
	}
	nd->flags &= ~LOOKUP_PARENT;
	/*检验返回结果*/
	if (nd->last_type == LAST_BIND)
		goto ok;
	error = -EISDIR;
	if (nd->last_type != LAST_NORM)
		goto exit;
	if (nd->last.name[nd->last.len]) {
		__putname(nd->last.name);
		goto exit;
	}
	error = -ELOOP;
	/*超出循环最大次数*/
	if (count++==32) {
		__putname(nd->last.name);
		goto exit;
	}
	/*填充返回结果*/
	dir = nd->dentry;
	mutex_lock(&dir->d_inode->i_mutex);
	path.dentry = lookup_hash(nd);
	path.mnt = nd->mnt;
	__putname(nd->last.name);
	goto do_last;
}


我们继续看open_namei_create函数，就是这个函数执行了文件的创建操作，open_namei_create函数定义如下
static int open_namei_create(struct nameidata *nd, struct path *path,
				int flag, int mode)
{
	int error;
	struct dentry *dir = nd->dentry;
	/*POSIX权限标准检查*/
	if (!IS_POSIXACL(dir->d_inode))
		mode &= ~current->fs->umask;
	/*vfs层调用文件创造*/
	error = vfs_create(dir->d_inode, path->dentry, mode, nd);
	mutex_unlock(&dir->d_inode->i_mutex);
	dput(nd->dentry);
	/*创建后放到nameidata里*/
	nd->dentry = path->dentry;
	if (error)
		return error;
	/*权限检查，不检查写权限和truncate权限*/
	return may_open(nd, 0, flag & ~O_TRUNC);
}



继续看vfs_create函数
int vfs_create(struct inode *dir, struct dentry *dentry, int mode,
		struct nameidata *nd)
{
	/*打开前的权限检查*/
	int error = may_create(dir, dentry, nd);
 
 
	if (error)
		return error;
	/*inode的inode_operation函数表的create函数*/
	if (!dir->i_op || !dir->i_op->create)
		return -EACCES;	/* shouldn't it be ENOSYS? */
	mode &= S_IALLUGO;
	mode |= S_IFREG;
	/*安全检查操作*/
	error = security_inode_create(dir, dentry, mode);
	if (error)
		return error;
	DQUOT_INIT(dir);
	/*创建*/
	error = dir->i_op->create(dir, dentry, mode, nd);
	if (!error)
		fsnotify_create(dir, dentry);
	return error;

